"""Orchestrates all scrapers and manages the scrape pipeline."""

import logging

from gamejobtracker.db.repository import JobRepository
from gamejobtracker.scrapers.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)


class ScraperManager:
    """Runs all configured scrapers and stores results."""

    def __init__(self, config: dict, repo: JobRepository):
        self.config = config
        self.repo = repo
        self.scrapers: list[BaseScraper] = []

    def register(self, scraper: BaseScraper) -> None:
        if scraper.is_available():
            self.scrapers.append(scraper)
            logger.info("Registered scraper: %s", scraper.source_name)
        else:
            logger.warning("Scraper not available: %s", scraper.source_name)

    def _get_query_groups(self) -> dict[str, list[dict]]:
        """Return query groups from config, supporting both old and new formats."""
        search_cfg = self.config.get("search", {})

        # New format: search.query_groups.{group_name}.queries
        if "query_groups" in search_cfg:
            return {
                name: group_cfg.get("queries", [])
                for name, group_cfg in search_cfg["query_groups"].items()
            }

        # Legacy format: search.queries (flat list, all go to "priority")
        queries = search_cfg.get("queries", [])
        return {"priority": queries} if queries else {}

    def run_all(self) -> list[tuple[int, ScrapedJob]]:
        """Run all scrapers for all configured query groups. Returns new jobs only."""
        query_groups = self._get_query_groups()
        all_new: list[tuple[int, ScrapedJob]] = []

        for scraper in self.scrapers:
            run_id = self.repo.start_scrape_run(scraper.source_name)
            total_found = 0
            total_new = 0

            try:
                for group_name, queries in query_groups.items():
                    for query_cfg in queries:
                        query_text = query_cfg.get("text", "")
                        locations = query_cfg.get("locations", [None])

                        for location in locations:
                            logger.info(
                                "[%s/%s] Searching: '%s' in %s",
                                scraper.source_name, group_name,
                                query_text, location or "anywhere",
                            )
                            try:
                                jobs = scraper.scrape(query_text, location)
                            except Exception:
                                logger.exception(
                                    "[%s/%s] Error scraping '%s' in %s",
                                    scraper.source_name, group_name,
                                    query_text, location,
                                )
                                continue

                            # Tag each job with its query group
                            for job in jobs:
                                job.query_group = group_name

                            total_found += len(jobs)
                            new_jobs = self.repo.upsert_jobs(jobs)
                            total_new += len(new_jobs)
                            all_new.extend(new_jobs)

                self.repo.complete_scrape_run(run_id, total_found, total_new)
                logger.info(
                    "[%s] Done — %d found, %d new",
                    scraper.source_name, total_found, total_new,
                )
            except Exception as e:
                logger.exception("[%s] Scrape run failed", scraper.source_name)
                self.repo.fail_scrape_run(run_id, str(e))

        return all_new

    def run_source(self, source_name: str) -> list[tuple[int, ScrapedJob]]:
        """Run a specific scraper by source name."""
        scraper = next(
            (s for s in self.scrapers if s.source_name == source_name), None
        )
        if not scraper:
            logger.error("Unknown scraper source: %s", source_name)
            return []

        # Temporarily swap scrapers list to reuse run_all logic
        original = self.scrapers
        self.scrapers = [scraper]
        result = self.run_all()
        self.scrapers = original
        return result
