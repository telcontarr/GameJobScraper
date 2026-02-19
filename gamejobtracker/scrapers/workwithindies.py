"""Work With Indies scraper — RSS feed parser."""

import logging
import re
from hashlib import sha256

import feedparser
import requests
from bs4 import BeautifulSoup

from gamejobtracker.scrapers.base import BaseScraper, ScrapedJob
from gamejobtracker.utils.text_processing import strip_html

logger = logging.getLogger(__name__)

RSS_URL = "https://workwithindies.com/careers/rss.xml"

# Keywords that indicate a design role relevant to the user
DESIGN_KEYWORDS = [
    "level design", "world design", "environment design", "game design",
    "level designer", "world designer", "environment designer", "game designer",
    "encounter design", "encounter designer", "content design", "content designer",
    "technical designer",
]


class WorkWithIndiesScraper(BaseScraper):
    source_name = "workwithindies"

    def __init__(self, config: dict):
        super().__init__(config)
        self.fetch_full = (
            config.get("scraping", {})
            .get("workwithindies", {})
            .get("fetch_full_descriptions", True)
        )

    def is_available(self) -> bool:
        enabled = (
            self.config.get("scraping", {})
            .get("workwithindies", {})
            .get("enabled", True)
        )
        return enabled

    def scrape(self, query: str, location: str | None = None) -> list[ScrapedJob]:
        """Fetch RSS feed and filter for design-related roles.

        The query/location params are used for local filtering since
        the RSS feed returns all jobs (no server-side search).
        """
        logger.info("Fetching Work With Indies RSS feed")
        feed = feedparser.parse(RSS_URL)

        if feed.bozo and not feed.entries:
            logger.error("Failed to parse RSS feed: %s", feed.bozo_exception)
            return []

        jobs = []
        query_lower = query.lower() if query else ""

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            guid = entry.get("id", "") or entry.get("guid", "") or link
            pub_date = entry.get("published", "")

            # Check if this entry matches design keywords or query
            combined_text = (title + " " + summary).lower()
            is_design_match = any(kw in combined_text for kw in DESIGN_KEYWORDS)
            is_query_match = query_lower and query_lower in combined_text

            if not (is_design_match or is_query_match):
                continue

            # Apply exclusion filters
            excludes = (
                self.config.get("search", {})
                .get("title_filters", {})
                .get("exclude", [])
            )
            if any(ex.lower() in title.lower() for ex in excludes):
                continue

            # Location filtering (basic string matching)
            if location and location.lower() != "remote":
                # Work With Indies doesn't always have structured location data
                # so we do a best-effort match
                if location.lower() not in combined_text:
                    continue

            # Parse company and title from RSS title
            # Format: "Company is hiring a Job Title to work from Location"
            company = "Unknown"
            title_clean = title
            hiring_match = re.match(
                r"^(.+?)\s+is hiring (?:a |an )?(.+?)(?:\s+to work from\s+.+)?$",
                title,
                re.IGNORECASE,
            )
            if hiring_match:
                company = hiring_match.group(1).strip()
                title_clean = hiring_match.group(2).strip()
            elif " at " in title:
                parts = title.rsplit(" at ", 1)
                title_clean = parts[0].strip()
                company = parts[1].strip()
            elif " - " in title:
                parts = title.split(" - ", 1)
                title_clean = parts[0].strip()
                company = parts[1].strip()

            # Fetch full description if configured
            description = strip_html(summary)
            description_raw = summary
            if self.fetch_full and link:
                full_desc = self._fetch_full_description(link)
                if full_desc:
                    description = full_desc["text"]
                    description_raw = full_desc["html"]

            is_remote = "remote" in combined_text.lower()

            external_id = sha256(guid.encode()).hexdigest()[:16]

            jobs.append(
                ScrapedJob(
                    external_id=external_id,
                    source=self.source_name,
                    url=link,
                    title=title_clean,
                    company=company,
                    location="Remote" if is_remote else None,
                    is_remote=is_remote,
                    description=description,
                    description_raw=description_raw,
                    date_posted=pub_date,
                )
            )

        logger.info("Work With Indies: %d matching jobs from RSS", len(jobs))
        return jobs

    def _fetch_full_description(self, url: str) -> dict | None:
        """Fetch the full job page and extract the description."""
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "GameJobTracker/0.1"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Work With Indies uses Webflow — look for the main content area
            desc_el = (
                soup.find("div", class_=re.compile(r"job.*(description|content|body)", re.I))
                or soup.find("div", class_="rich-text-block")
                or soup.find("article")
                or soup.find("main")
            )

            if desc_el:
                return {
                    "html": str(desc_el),
                    "text": desc_el.get_text(separator=" ", strip=True),
                }
        except Exception:
            logger.debug("Failed to fetch full description from %s", url, exc_info=True)

        return None
