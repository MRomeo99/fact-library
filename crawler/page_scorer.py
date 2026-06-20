"""Page importance scoring model."""
import re
from typing import Optional
from bs4 import BeautifulSoup

# Default page type scores (0–5)
DEFAULT_PAGE_TYPE_RULES: list[tuple[str, int]] = [
    # Score 0 — skip entirely
    ("/privacy", 0),
    ("/terms", 0),
    ("/legal", 0),
    # Score 1
    ("/contact", 1),
    ("/get-in-touch", 1),
    # Score 2
    ("/blog", 2),
    ("/news", 2),
    ("/reviews", 2),
    ("/testimonials", 2),
    # Score 3
    ("/locations", 3),
    ("/service-area", 3),
    ("/faq", 3),
    ("/help", 3),
    ("/questions", 3),
    # Score 4
    ("/about", 4),
    ("/team", 4),
    ("/our-story", 4),
    ("/pricing", 4),
    ("/packages", 4),
    ("/rates", 4),
    # Score 5
    ("/services", 5),
    ("/treatments", 5),
    ("/solutions", 5),
]

HOMEPAGE_PATTERNS = {"/", "/index"}


class PageScorer:
    def __init__(self, config: Optional[dict] = None):
        self._rules = list(DEFAULT_PAGE_TYPE_RULES)
        self.top_x = 10
        if config:
            for override in config.get("page_type_overrides", []):
                self._rules.insert(0, (override["pattern"], override["score"]))
            if "top_x_pages" in config:
                self.top_x = config["top_x_pages"]

    def score_url(self, path: str) -> int:
        """Return the base importance score for the given URL path."""
        # Normalise to lowercase
        p = path.lower()

        # Exact homepage matches
        if p == "/" or p == "/index" or p == "/index.html":
            return 4

        # Check date-in-URL pattern → blog
        if re.search(r"/\d{4}[-/]\d{2}", p):
            return 2

        # City-name-in-URL → locations (heuristic)
        # handled via "service-area" below; skip city detection for simplicity

        # Walk rules longest-first so more specific patterns win
        sorted_rules = sorted(self._rules, key=lambda r: -len(r[0]))
        for pattern, score in sorted_rules:
            if pattern in p:
                return score

        # Default unknown pages score 2
        return 2

    def compute_modifiers(self, html: str, inbound_links: int) -> dict:
        """Return a dict of modifier contributions."""
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator=" ")
        word_count = len(text.split())

        json_ld = 1.0 if soup.find("script", {"type": "application/ld+json"}) else 0.0
        h2h3 = len(soup.find_all(["h2", "h3"]))
        dollar_fee = bool(re.search(r"(\$[\d,]+|fee\b)", text, re.IGNORECASE))

        return {
            "json_ld": json_ld,
            "word_count": 0.5 if word_count > 300 else 0.0,
            "headings": 0.5 if h2h3 > 3 else 0.0,
            "inbound_links": 0.5 if inbound_links > 5 else 0.0,
            "price_signals": 0.5 if dollar_fee else 0.0,
        }

    def score_page(self, path: str, html: str, inbound_links: int = 0) -> float:
        """Return the total capped score (0–5) for a page."""
        base = self.score_url(path)
        mods = self.compute_modifiers(html, inbound_links)
        total = base + sum(mods.values())
        return min(total, 5)


def score_page(path: str, html: str, inbound_links: int = 0) -> float:
    """Module-level convenience wrapper."""
    return PageScorer().score_page(path, html, inbound_links)
