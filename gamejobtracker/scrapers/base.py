"""Base scraper class and ScrapedJob data model."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScrapedJob:
    """Standardized job data from any scraper."""

    external_id: str
    source: str
    url: str
    title: str
    company: str
    location: str | None = None
    is_remote: bool = False
    description: str | None = None
    description_raw: str | None = None
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    date_posted: str | None = None
    query_group: str = "priority"
    date_scraped: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class BaseScraper(ABC):
    """Abstract base class for all job board scrapers."""

    source_name: str = ""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def scrape(self, query: str, location: str | None = None) -> list[ScrapedJob]:
        """Run a search and return standardized job listings."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this scraper is properly configured and reachable."""
        ...
