"""JSearch API scraper — aggregates Indeed, LinkedIn, Glassdoor via RapidAPI."""

import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from gamejobtracker.scrapers.base import BaseScraper, ScrapedJob
from gamejobtracker.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

API_URL = "https://jsearch.p.rapidapi.com/search"
API_HOST = "jsearch.p.rapidapi.com"


class JSearchScraper(BaseScraper):
    source_name = "jsearch"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_keys", {}).get("rapidapi", "")
        scraping_cfg = config.get("scraping", {}).get("jsearch", {})
        self.date_filter = scraping_cfg.get("date_filter", "3days")
        self.pages_per_query = scraping_cfg.get("pages_per_query", 2)
        self.results_per_page = scraping_cfg.get("results_per_page", 10)
        self.rate_limiter = RateLimiter(calls_per_minute=5)

    def is_available(self) -> bool:
        enabled = (
            self.config.get("scraping", {}).get("jsearch", {}).get("enabled", True)
        )
        return enabled and bool(self.api_key)

    def scrape(self, query: str, location: str | None = None) -> list[ScrapedJob]:
        jobs = []
        for page in range(1, self.pages_per_query + 1):
            page_jobs = self._fetch_page(query, location, page)
            jobs.extend(page_jobs)
            if len(page_jobs) < self.results_per_page:
                break  # No more results
        return jobs

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
    )
    def _fetch_page(self, query: str, location: str | None, page: int) -> list[ScrapedJob]:
        self.rate_limiter.wait("jsearch")

        params = {
            "query": query,
            "page": str(page),
            "num_pages": "1",
            "date_posted": self.date_filter,
        }

        if location:
            if location.lower() == "remote":
                params["remote_jobs_only"] = "true"
            else:
                params["query"] = f"{query} in {location}"

        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": API_HOST,
        }

        logger.debug("JSearch request: query='%s', page=%d", params["query"], page)
        resp = requests.get(API_URL, headers=headers, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning("JSearch rate limit hit — backing off")
            raise requests.exceptions.RequestException("Rate limited")

        resp.raise_for_status()
        data = resp.json()

        results = data.get("data", [])
        logger.debug("JSearch page %d: %d results", page, len(results))

        jobs = []
        for item in results:
            job = self._parse_item(item)
            if job:
                jobs.append(job)

        return jobs

    def _parse_item(self, item: dict) -> ScrapedJob | None:
        job_id = item.get("job_id", "")
        title = item.get("job_title", "")
        company = item.get("employer_name", "Unknown")
        url = item.get("job_apply_link") or item.get("job_google_link", "")

        if not title or not url:
            return None

        # Location
        city = item.get("job_city", "")
        state = item.get("job_state", "")
        country = item.get("job_country", "")
        location_parts = [p for p in [city, state, country] if p]
        location = ", ".join(location_parts) if location_parts else None

        is_remote = item.get("job_is_remote", False)

        description = item.get("job_description", "")
        employment_type = item.get("job_employment_type", "")

        salary_min = item.get("job_min_salary")
        salary_max = item.get("job_max_salary")
        salary_currency = item.get("job_salary_currency")

        date_posted = item.get("job_posted_at_datetime_utc", "")

        # Apply exclusion filters from config
        excludes = (
            self.config.get("search", {})
            .get("title_filters", {})
            .get("exclude", [])
        )
        if any(ex.lower() in title.lower() for ex in excludes):
            return None

        return ScrapedJob(
            external_id=job_id,
            source=self.source_name,
            url=url,
            title=title,
            company=company,
            location=location,
            is_remote=is_remote,
            description=description,
            employment_type=employment_type,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            date_posted=date_posted,
        )
