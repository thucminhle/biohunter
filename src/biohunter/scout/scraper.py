from __future__ import annotations

import hashlib
import urllib.parse

import requests
from bs4 import BeautifulSoup

from ..ats.base import RawPosting
from .ratelimit import RateLimiter, _USER_AGENT


def fetch_page(url: str, limiter: RateLimiter) -> str:
    if not limiter.allowed_by_robots(url):
        raise PermissionError(f"robots.txt disallows fetching {url}")
    limiter.wait_for_domain(url)
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.text


def content_hash(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def extract_postings(html: str, css_selector: str, base_url: str) -> list[RawPosting]:
    """Structured scrape: css_selector should match anchor tags (or elements
    containing an anchor) for individual job listings. This is intentionally
    simple -- per the design doc, each self-hosted company gets its own
    selector configured in companies.yaml once you've inspected its page;
    there's no generic "parse any careers page" magic here.
    """
    soup = BeautifulSoup(html, "html.parser")
    postings = []
    for el in soup.select(css_selector):
        anchor = el if el.name == "a" else el.find("a")
        if anchor is None or not anchor.get("href"):
            continue
        title = anchor.get_text(strip=True)
        href = urllib.parse.urljoin(base_url, anchor["href"])
        if title:
            postings.append(RawPosting(title=title, url=href))
    return postings


def check_for_change(html: str, previous_hash: str | None) -> tuple[bool, str]:
    """Returns (changed, new_hash). If css_selector-based extraction later
    yields zero postings despite a hash change, Scout should flag the
    company for manual selector review (design doc §4, detection strategy #3)."""
    new_hash = content_hash(html)
    changed = previous_hash is None or new_hash != previous_hash
    return changed, new_hash
