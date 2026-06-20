"""Abstract base class for all crawlers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CrawledPage:
    url: str
    html: str
    status_code: int
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    error: Optional[str] = None


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
