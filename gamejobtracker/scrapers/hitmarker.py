"""Hitmarker scraper — game industry job board (JS-rendered).

Hitmarker is a client-side rendered site backed by Typesense search.
This scraper uses Playwright to render the page and extract job data.

Each job card is an <a> element with inner_text() structured as:
    \\u200b           (zero-width space — skip)
    Title
    Company
    Location(s)      (may span multiple lines)
    Employment Type  (Full Time / Contract / etc.)
    Seniority        (Senior (5+ years) / etc.)
    Salary           (optional)
    Time ago
    Bookmark

Since the /game-design-jobs page already filters to design roles,
we scrape it once and filter locally by title keywords and location
rather than re-loading per query.
"""

import logging
import re
from hashlib import sha256
from urllib.parse import urljoin

from gamejobtracker.scrapers.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

BASE_URL = "https://hitmarker.net"
CATEGORY_URL = f"{BASE_URL}/game-design-jobs"

# Known non-location, non-title tokens that help us find where location ends
EMPLOYMENT_TYPES = {"full time", "part time", "contract", "temp", "freelance", "internship"}
SENIORITY_MARKERS = {"senior", "intermediate", "junior", "entry", "lead", "director"}


def _parse_card_text(text: str) -> dict | None:
    """Parse the structured inner_text of a Hitmarker job card."""
    lines = [l.strip() for l in text.split("\n") if l.strip() and l.strip() != "\u200b"]
    if len(lines) < 3:
        return None

    title = lines[0]
    company = lines[1]

    # Lines 2+ contain location(s), employment type, seniority, salary, time ago, Bookmark
    # Locations come first, then a line matching an employment type keyword
    location_lines = []
    remaining_start = 2
    for i in range(2, len(lines)):
        line_lower = lines[i].lower()
        # Stop collecting locations when we hit employment type or seniority/time
        if any(et in line_lower for et in EMPLOYMENT_TYPES):
            remaining_start = i
            break
        if re.match(r"\d+ (hour|day|week|month)s? ago", line_lower):
            remaining_start = i
            break
        if "bookmark" in line_lower:
            remaining_start = i
            break
        location_lines.append(lines[i])

    location = ", ".join(location_lines) if location_lines else ""

    # Extract salary from remaining lines (pattern: $xxx or CA$xxx or €xxx)
    salary_min = None
    salary_max = None
    for line in lines[remaining_start:]:
        salary_match = re.search(
            r"[\$€£][\d,]+(?:\.?\d*)\s*[-–]\s*[\$€£]?[\d,]+(?:\.?\d*)",
            line,
        )
        if salary_match:
            numbers = re.findall(r"[\d,]+(?:\.\d+)?", salary_match.group())
            if len(numbers) >= 2:
                salary_min = float(numbers[0].replace(",", ""))
                salary_max = float(numbers[1].replace(",", ""))
            break

    return {
        "title": title,
        "company": company,
        "location": location,
        "salary_min": salary_min,
        "salary_max": salary_max,
    }


class HitmarkerScraper(BaseScraper):
    """Scrapes Hitmarker using a headless browser (Playwright)."""

    source_name = "hitmarker"

    def __init__(self, config: dict):
        super().__init__(config)
        self._cached_jobs: list[ScrapedJob] | None = None

    def is_available(self) -> bool:
        enabled = (
            self.config.get("scraping", {})
            .get("hitmarker", {})
            .get("enabled", True)
        )
        if not enabled:
            return False

        try:
            import playwright
            return True
        except ImportError:
            logger.warning(
                "Hitmarker scraper requires playwright. "
                "Install with: pip install playwright && python -m playwright install chromium"
            )
            return False

    def scrape(self, query: str, location: str | None = None) -> list[ScrapedJob]:
        """Scrape Hitmarker game-design-jobs page, filter by query and location.

        The page is fetched once and cached across calls within the same run.
        """
        # Fetch all jobs from the page (cached after first call)
        if self._cached_jobs is None:
            self._cached_jobs = self._fetch_all_jobs()

        # Filter by query and location
        return self._filter_jobs(self._cached_jobs, query, location)

    def _fetch_all_jobs(self) -> list[ScrapedJob]:
        """Load the Hitmarker page and extract all job listings."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed — skipping Hitmarker")
            return []

        all_jobs = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                logger.info("Hitmarker: loading %s", CATEGORY_URL)
                page.goto(CATEGORY_URL, timeout=30000)
                page.wait_for_selector("a[href*='/jobs/']", timeout=15000)

                # Scroll to load more results
                for _ in range(5):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                job_elements = page.query_selector_all("a[href*='/jobs/']")
                logger.info("Hitmarker: found %d job link elements", len(job_elements))

                seen_urls = set()

                for el in job_elements:
                    try:
                        href = el.get_attribute("href") or ""
                        url = href if href.startswith("http") else urljoin(BASE_URL, href)

                        if url in seen_urls:
                            continue
                        seen_urls.add(url)

                        text = el.inner_text()
                        parsed = _parse_card_text(text)
                        if not parsed:
                            continue

                        is_remote = "remote" in (parsed["location"]).lower()

                        # Extract numeric ID from URL
                        id_match = re.search(r"-(\d+)$", href)
                        external_id = (
                            id_match.group(1)
                            if id_match
                            else sha256(url.encode()).hexdigest()[:16]
                        )

                        all_jobs.append(
                            ScrapedJob(
                                external_id=external_id,
                                source=self.source_name,
                                url=url,
                                title=parsed["title"],
                                company=parsed["company"],
                                location=parsed["location"] or ("Remote" if is_remote else None),
                                is_remote=is_remote,
                                salary_min=parsed["salary_min"],
                                salary_max=parsed["salary_max"],
                                salary_currency="USD" if parsed["salary_min"] else None,
                            )
                        )
                    except Exception:
                        logger.debug("Error parsing Hitmarker element", exc_info=True)
                        continue

                browser.close()

        except Exception:
            logger.exception("Hitmarker scrape failed")

        logger.info("Hitmarker: %d total jobs extracted from page", len(all_jobs))
        return all_jobs

    def _filter_jobs(
        self, jobs: list[ScrapedJob], query: str, location: str | None
    ) -> list[ScrapedJob]:
        """Filter cached jobs by query keywords and location."""
        query_lower = query.lower()
        query_words = query_lower.split()

        excludes = (
            self.config.get("search", {})
            .get("title_filters", {})
            .get("exclude", [])
        )

        filtered = []
        for job in jobs:
            title_lower = job.title.lower()

            # Query matching: check if ALL query words appear in the title
            # e.g. "Level Designer" -> both "level" and "designer" must be in title
            if not all(w in title_lower for w in query_words):
                continue

            # Apply exclusion filters
            if any(ex.lower() in title_lower for ex in excludes):
                continue

            # Location filtering
            if location and location.lower() == "remote":
                if not job.is_remote:
                    continue
            elif location:
                loc_lower = (job.location or "").lower()
                if location.lower() not in loc_lower and not job.is_remote:
                    continue

            filtered.append(job)

        return filtered
