"""JS-rendered fallback crawler using Playwright."""
import logging
from typing import Optional

from crawler.base import AbstractCrawler, CrawledPage
from crawler.robots import get_robots_parser, is_allowed, USER_AGENT

logger = logging.getLogger(__name__)


class PlaywrightCrawler(AbstractCrawler):
    """Opt-in crawler for JS-rendered SPAs. Requires `playwright install chromium`."""

    def __init__(self, rate_limit_seconds: float = 2.0, timeout_ms: int = 15_000):
        self._rate_limit = rate_limit_seconds
        self._timeout_ms = timeout_ms
        self._robots_cache: dict[str, object] = {}

    def _get_robots(self, url: str):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots_cache:
            self._robots_cache[origin] = get_robots_parser(url)
        return self._robots_cache[origin]

    def fetch(self, url: str) -> CrawledPage:
        robots = self._get_robots(url)
        if not is_allowed(url, robots):
            return CrawledPage(url=url, html="", status_code=0, error="disallowed by robots.txt")

        try:
            from playwright.sync_api import sync_playwright
            import time
            time.sleep(self._rate_limit)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=f"{USER_AGENT} (Playwright)")
                response = page.goto(url, timeout=self._timeout_ms, wait_until="networkidle")
                html = page.content()
                status = response.status if response else 0
                browser.close()
            return CrawledPage(url=url, html=html, status_code=status)
        except Exception as exc:
            logger.error("Playwright error fetching %s: %s", url, exc)
            return CrawledPage(url=url, html="", status_code=0, error=str(exc))

    def discover_links(self, base_url: str, html: str) -> list[str]:
        from urllib.parse import urljoin, urlparse
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        parsed_base = urlparse(base_url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            absolute = urljoin(base_url, tag["href"])
            if absolute.startswith(base_origin):
                clean = absolute.split("#")[0].rstrip("/") or "/"
                if clean not in links:
                    links.append(clean)
        return links
