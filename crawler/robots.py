"""robots.txt fetching and enforcement."""
import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "ClientFactLibrary/1.0"
logger = logging.getLogger(__name__)


def get_robots_parser(base_url: str) -> RobotFileParser:
    """Fetch and parse robots.txt for the given domain."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception as exc:
        logger.warning("Could not fetch robots.txt for %s: %s", base_url, exc)
    return parser


def is_allowed(url: str, parser: RobotFileParser) -> bool:
    """Return True if the URL is allowed to be crawled."""
    return parser.can_fetch(USER_AGENT, url)
