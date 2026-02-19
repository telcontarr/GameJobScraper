"""GameJobs.co scraper — HTML scraping of game industry job board.

GameJobs.co HTML structure (discovered via inspection):
    <div class="job">
        <a class="title" href="/Job-Title-at-Company-1234">Job Title</a>
        <div>
            <a class="c" href="/search?c=Company">Company Name</a>
            <a class="w" href="/search?w=City">City, Country</a>
            ...
        </div>
    </div>

Note: Title links contain <em> tags for search highlighting,
so we must use get_text(separator=" ") to preserve word spacing.
"""

import logging
import re
import time
import random
from hashlib import sha256
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from gamejobtracker.scrapers.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

BASE_URL = "https://gamejobs.co"
SEARCH_URL = f"{BASE_URL}/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class GameJobsCoScraper(BaseScraper):
    source_name = "gamejobsco"

    def __init__(self, config: dict):
        super().__init__(config)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def is_available(self) -> bool:
        return (
            self.config.get("scraping", {})
            .get("gamejobsco", {})
            .get("enabled", True)
        )

    def scrape(self, query: str, location: str | None = None) -> list[ScrapedJob]:
        """Search GameJobs.co and parse results."""
        jobs = []

        # Build search URL
        search_query = query
        if location and location.lower() != "remote":
            search_query = f"{query} {location}"

        url = f"{SEARCH_URL}?q={quote_plus(search_query)}"

        logger.info("GameJobs.co: searching '%s'", search_query)

        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("GameJobs.co: failed to fetch search results")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # GameJobs.co uses <div class="job"> for each listing
        job_divs = soup.find_all("div", class_="job")

        if not job_divs:
            logger.info("GameJobs.co: no results found for '%s'", search_query)
            return []

        logger.debug("GameJobs.co: found %d job divs", len(job_divs))

        excludes = (
            self.config.get("search", {})
            .get("title_filters", {})
            .get("exclude", [])
        )

        for div in job_divs:
            job = self._parse_job_div(div, excludes, location)
            if job:
                jobs.append(job)

        logger.info("GameJobs.co: %d matching jobs for '%s'", len(jobs), search_query)
        return jobs

    def _parse_job_div(self, div, excludes: list, location: str | None) -> ScrapedJob | None:
        """Extract job data from a <div class="job"> element."""
        # Title: <a class="title" href="...">Job Title</a>
        # Use separator=" " to preserve spacing between <em> tags
        title_el = div.find("a", class_="title")
        if not title_el:
            return None

        title = title_el.get_text(separator=" ", strip=True)
        # Collapse any double spaces from <em> tag joins
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            return None

        # Apply exclusion filters
        if any(ex.lower() in title.lower() for ex in excludes):
            return None

        # URL
        href = title_el.get("href", "")
        url = urljoin(BASE_URL, href) if href else ""
        if not url:
            return None

        # Company: <a class="c" href="/search?c=...">Company Name</a>
        company_el = div.find("a", class_="c")
        company = company_el.get_text(strip=True) if company_el else ""

        # Fallback: extract company from URL (format: /Title-at-Company-1234)
        if not company and "-at-" in href:
            url_match = re.search(r"-at-(.+?)(?:-\d+)?$", href)
            if url_match:
                company = url_match.group(1).replace("-", " ")

        if not company:
            company = "Unknown"

        # Location: <a class="w" href="/search?w=...">City, Country</a>
        loc_el = div.find("a", class_="w")
        loc_text = loc_el.get_text(strip=True) if loc_el else ""

        is_remote = "remote" in (title + " " + loc_text).lower()

        # Location filtering
        if location and location.lower() == "remote" and not is_remote:
            return None
        if location and location.lower() != "remote":
            if location.lower() not in (title + " " + loc_text).lower() and not is_remote:
                return None

        # External ID: use numeric ID from URL if present, else hash
        id_match = re.search(r"-(\d+)$", href)
        external_id = id_match.group(1) if id_match else sha256(url.encode()).hexdigest()[:16]

        return ScrapedJob(
            external_id=external_id,
            source=self.source_name,
            url=url,
            title=title,
            company=company,
            location=loc_text or ("Remote" if is_remote else None),
            is_remote=is_remote,
        )
