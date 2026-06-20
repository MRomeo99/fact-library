"""Default static crawler using httpx + BeautifulSoup."""
import logging
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from crawler.base import AbstractCrawler, CrawledPage
from crawler.robots import get_robots_parser, is_allowed, USER_AGENT

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": f"{USER_AGENT} (+https://github.com/your-org/client-fact-library)",
}


class HttpxCrawler(AbstractCrawler):
    def __init__(self, rate_limit_seconds: float = 1.5, timeout: float = 15.0):
        self._rate_limit = rate_limit_seconds
        self._timeout = timeout
        self._robots_cache: dict[str, object] = {}

    def _get_robots(self, base_url: str):
        origin = _origin(base_url)
        if origin not in self._robots_cache:
            self._robots_cache[origin] = get_robots_parser(base_url)
        return self._robots_cache[origin]

    def fetch(self, url: str) -> CrawledPage:
        robots = self._get_robots(url)
        if not is_allowed(url, robots):
            logger.info("robots.txt disallows %s", url)
            return CrawledPage(url=url, html="", status_code=0, error="disallowed by robots.txt")

        try:
            time.sleep(self._rate_limit)
            with httpx.Client(headers=DEFAULT_HEADERS, timeout=self._timeout, follow_redirects=True) as c:
                response = c.get(url)
            return CrawledPage(
                url=str(response.url),
                html=response.text,
                status_code=response.status_code,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
            return CrawledPage(url=url, html="", status_code=0, error=str(exc))

    def discover_links(self, base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        base_origin = _origin(base_url)
        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            # Internal links only, strip fragments
            if _origin(absolute) == base_origin and parsed.scheme in ("http", "https"):
                clean = absolute.split("#")[0].rstrip("/") or "/"
                if clean not in links:
                    links.append(clean)
        return links


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"
