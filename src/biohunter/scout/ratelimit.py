from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser

import requests

# Design doc: "keep checks to 1x/day or a few hours apart per company."
# This tracks last-fetch-time per domain in-process; since Scout runs as a
# scheduled batch job (not a long-lived daemon), persistent cross-run
# enforcement lives in companies.last_checked_at (checked by the caller
# before it even gets here) -- this class just prevents hammering the same
# domain within a single run (e.g. several companies on api.greenhouse.io).
MIN_SECONDS_BETWEEN_REQUESTS_SAME_DOMAIN = 2.0

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"

_ROBOTS_FETCH_TIMEOUT = 10


class RateLimiter:
    def __init__(self, min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS_SAME_DOMAIN):
        self._min_interval = min_interval
        self._last_request_at: dict[str, float] = {}
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def wait_for_domain(self, url: str) -> None:
        domain = urllib.parse.urlparse(url).netloc
        last = self._last_request_at.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at[domain] = time.monotonic()

    def allowed_by_robots(self, url: str) -> bool:
        """Only meaningful for the fallback scraper -- ATS API calls hit a
        documented API surface, not a scraped page, so robots.txt doesn't
        apply there the same way. Fail-open (allow) if robots.txt can't be
        fetched, since its absence isn't a disallow signal.

        Deliberately does NOT use RobotFileParser.read() -- that method
        does its own internal network fetch with Python's default urllib
        User-Agent (no way to pass it our own _USER_AGENT), and stdlib
        RobotFileParser sets disallow_all=True on ANY 401/403 response to
        THAT fetch. Real bug hit this session: a site whose bot-protection
        blocks generic/header-less Python requests returns 403 to the
        robots.txt fetch itself, which silently blocks EVERYTHING for that
        domain -- with zero relationship to what the file actually says.
        Confirmed against two real companies (AbbVie, Pacific Biolabs)
        whose actual robots.txt content, read directly, permits the exact
        URLs that got blocked. Fetching with requests + our real
        _USER_AGENT first, then handing the text to rp.parse() (which does
        no network I/O), sidesteps that failure mode while keeping the
        same fail-open philosophy as before for genuine fetch failures.
        """
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
        rp = self._robots_cache.get(domain)
        if rp is not None:
            return rp.can_fetch(_USER_AGENT, url)

        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        rp.set_url(robots_url)
        try:
            resp = requests.get(robots_url, headers={"User-Agent": _USER_AGENT}, timeout=_ROBOTS_FETCH_TIMEOUT)
        except Exception:
            # Couldn't fetch robots.txt at all -- don't block on that basis.
            rp.allow_all = True
            self._robots_cache[domain] = rp
            return True

        if resp.status_code in (401, 403):
            # Matches stdlib RobotFileParser.read()'s own documented
            # convention: treat an auth-walled/forbidden robots.txt as "this
            # site wants no bots". Preserved deliberately -- the bug fixed
            # here is WHICH User-Agent triggers this, not whether a real
            # 401/403 should mean disallow.
            rp.disallow_all = True
        elif 400 <= resp.status_code < 500:
            # Any other 4xx (most commonly 404, no robots.txt present at
            # all): its absence isn't a disallow signal.
            rp.allow_all = True
        elif resp.status_code >= 500:
            # Server error fetching robots.txt -- don't block on that basis,
            # same fail-open reasoning as an unreachable host.
            rp.allow_all = True
        else:
            rp.parse(resp.text.splitlines())

        self._robots_cache[domain] = rp
        return rp.can_fetch(_USER_AGENT, url)
