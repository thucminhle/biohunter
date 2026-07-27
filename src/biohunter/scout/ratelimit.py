from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser

# Design doc: "keep checks to 1x/day or a few hours apart per company."
# This tracks last-fetch-time per domain in-process; since Scout runs as a
# scheduled batch job (not a long-lived daemon), persistent cross-run
# enforcement lives in companies.last_checked_at (checked by the caller
# before it even gets here) -- this class just prevents hammering the same
# domain within a single run (e.g. several companies on api.greenhouse.io).
MIN_SECONDS_BETWEEN_REQUESTS_SAME_DOMAIN = 2.0

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"


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
        fetched, since its absence isn't a disallow signal."""
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
        rp = self._robots_cache.get(domain)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{parsed.scheme}://{domain}/robots.txt"
            rp.set_url(robots_url)
            try:
                rp.read()
            except Exception:
                # Couldn't fetch robots.txt -- don't block on that basis.
                self._robots_cache[domain] = rp
                return True
            self._robots_cache[domain] = rp
        return rp.can_fetch(_USER_AGENT, url)
