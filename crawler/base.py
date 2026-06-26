"""Abstract base class for all crawlers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CrawledPage:
    url: str
    html: str
    status_code: int
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


class AbstractCrawler(ABC):
    """Defines the interface all crawler implementations must satisfy."""

    @abstractmethod
    def fetch(self, url: str) -> CrawledPage:
        """Fetch a single URL and return a CrawledPage."""
        ...

    @abstractmethod
    def discover_links(self, base_url: str, html: str) -> list[str]:
        """Extract all internal links from an HTML page."""
        ...
