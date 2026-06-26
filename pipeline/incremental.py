"""Content hash comparison logic for incremental crawls."""

import hashlib


def compute_content_hash(
    url: str,
    content: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> str:
    """Compute a deterministic sha256 hash for a page.

    Prefers etag/last-modified cache validators when available;
    falls back to hashing the URL + raw content.
    """
    if etag:
        raw = f"{url}:etag:{etag}"
    elif last_modified:
        raw = f"{url}:lastmod:{last_modified}"
    elif content:
        raw = f"{url}:content:{content}"
    else:
        raw = url
    return hashlib.sha256(raw.encode()).hexdigest()


class ContentHashChecker:
    def __init__(self, store):
        self._store = store

    def should_crawl(self, client_id: str, url: str, content_hash: str) -> bool:
        """Return True if the page should be re-crawled (hash changed or unseen)."""
        return not self._store.content_hash_exists(
            client_id=client_id,
            source_url=url,
            content_hash=content_hash,
        )
