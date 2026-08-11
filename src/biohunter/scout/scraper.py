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


def check_url_alive(url: str, limiter: RateLimiter) -> tuple[bool | None, str]:
    """Checks whether a stored posting URL still resolves to a real
    listing, for the dashboard's dead-link sweep -- the "I clicked
    original posting and got a 404" problem, done at scale instead of
    one posting at a time.

    Returns (is_alive, detail):
      - (False, "HTTP 404") / (False, "HTTP 410") -- confidently dead.
        404/410 are the two status codes that specifically mean "this
        resource is gone", per HTTP semantics; nothing else is treated
        as a confident dead-link signal here.
      - (True, "HTTP 200") -- confidently alive.
      - (None, "...") -- COULD NOT DETERMINE. Covers robots.txt
        disallowing the check, network errors/timeouts, and any other
        status code (3xx redirects settled by requests already, 401/403
        bot-blocking that says nothing about whether the posting itself
        still exists, 5xx transient server errors). Deliberately NOT
        treated as "dead" -- a bot-blocked or flaky page is not the same
        claim as "this job posting no longer exists", and this
        function's whole purpose is to feed a human-reviewed "mark
        these as stale?" list, not to auto-delete anything. A False
        positive here (a live posting wrongly marked stale) is worse
        than a False negative (a dead posting not yet caught), so this
        errs toward under-claiming "dead", not over-claiming it.

    Uses GET, not HEAD: several ATS platforms (confirmed inconsistent
    behavior across Workday/Greenhouse/Lever in practice) return
    different status codes for HEAD vs GET on the same URL, and a
    dead-link check's whole job is to match what a human clicking the
    link would actually see. `stream=True` + immediately closing avoids
    downloading the full page body for a check that only needs the
    status line.

    Respects robots.txt and per-domain rate limiting via the SAME
    RateLimiter instance callers already use for Scout's own fetching --
    a bulk dead-link sweep across hundreds of postings hits the same
    ATS domains Scout does and must not hammer them outside Scout's
    existing politeness rules.
    """
    if not limiter.allowed_by_robots(url):
        return None, "robots.txt disallows checking this URL"
    limiter.wait_for_domain(url)
    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=15,
            stream=True, allow_redirects=True,
        )
        resp.close()
    except requests.RequestException as exc:
        return None, f"request failed: {exc}"

    if resp.status_code in (404, 410):
        return False, f"HTTP {resp.status_code}"
    if resp.status_code == 200:
        return True, "HTTP 200"
    return None, f"HTTP {resp.status_code} (inconclusive, not treated as dead)"
