"""
MC-308: On-demand Craigslist listing photo fetcher.

Craigslist search pages don't include photos (verified in MC-307 self-audit).
This module fetches a single listing page on demand and extracts the first
photo URL. Results are cached by `listing_url` with a 14-day TTL (positive
hits) and 1-hour TTL (negative hits: 404/timeout/parse-fail/403) to avoid
hammering Craigslist from the cron pipeline.

Rate-limit policy: 1 req/sec, max 30 fetches per cron cycle (server-side
token bucket via the calling endpoint in app.py).
"""

from __future__ import annotations

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup


# Browser-like headers: Craigslist blocks default Python user-agent strings
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Match http(s) URLs only (block javascript:, data:, mailto: schemes)
_HTTP_URL_RE = re.compile(r"^https?://[^\s'\"]+", re.IGNORECASE)


def _extract_og_image(html: str) -> Optional[str]:
    """
    Return og:image URL from <meta property="og:image" content="..."> or
    fallback to first img[src] with http URL.

    Returns None if no usable image URL found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Prefer og:image (always first picture on a CL listing)
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        url = og["content"].strip()
        if _HTTP_URL_RE.match(url):
            return url

    # Fallback: img#thumbs or first <img> with reasonable http(s) src
    thumbs_div = soup.find(id="thumbs")
    if thumbs_div:
        img = thumbs_div.find("img")
        if img and img.get("src"):
            url = img["src"].strip()
            if _HTTP_URL_RE.match(url):
                return url

    # Last resort: first <img src="http..."> in document
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if _HTTP_URL_RE.match(src) and "icon" not in src.lower() and "logo" not in src.lower():
            return src

    return None


def fetch_listing_photo(
    listing_url: str,
    *,
    session: Optional[requests.Session] = None,
    timeout: float = 15.0,
) -> Optional[str]:
    """
    Fetch a single Craigslist listing page and return its first photo URL.

    Returns None on:
    - 4xx/5xx status
    - network/timeout
    - parse failure
    - no image found on page

    Caller is expected to handle caching and rate limiting.
    """
    sess = session or requests.Session()
    own_session = session is None
    try:
        if own_session:
            sess.headers.update(HEADERS)
        r = sess.get(listing_url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None
        # Craigslist never serves as image-only; check content-type defensively
        ctype = (r.headers.get("content-type") or "").lower()
        if ctype and "html" not in ctype and "text" not in ctype:
            return None
        return _extract_og_image(r.text)
    except requests.RequestException:
        return None
    finally:
        if own_session:
            sess.close()


__all__ = ["fetch_listing_photo", "_extract_og_image"]
# MC-308 endpoint lives here
