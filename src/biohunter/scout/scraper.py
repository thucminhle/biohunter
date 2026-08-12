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


def _check_workday_url_alive(url: str, limiter: RateLimiter) -> tuple[bool | None, str]:
    """Workday-specific existence check, dispatched to by check_url_alive()
    below for any *.myworkdayjobs.com URL.

    WHY THIS EXISTS: fetching a Workday posting's PUBLIC page (what
    check_url_alive's generic path does) always returns HTTP 200,
    whether the job exists or not -- confirmed directly against a known-
    dead Amgen posting during this session. Workday's public job page is
    a client-rendered SPA shell; the real "does this job still exist"
    answer only appears after browser JavaScript calls Workday's internal
    CXS API, which a plain GET never executes. Status-code checking is
    categorically blind here, not just less reliable.

    THE SIGNAL USED INSTEAD, reused rather than invented: ats/workday.py's
    own _fetch_description() already established that a 200 response
    from the CXS detail endpoint with an EMPTY jobPostingInfo means "this
    posting may have been pulled/filled since the list call" -- that
    function already logs a warning for exactly this case, it just never
    turned the observation into an action. This function reuses that same
    endpoint shape (GET /wday/cxs/{tenant}/{site}{external_path}) and the
    same signal, just acting on it instead of only logging it.

    Derives tenant/site/external_path from the STORED POSTING URL alone
    (matches _fetch_one_site()'s own "https://{host}/{site}{external_path}"
    construction) rather than requiring company config lookup -- so this
    works standalone from just the url column, the same input
    check_url_alive() already gets.

    CONFIDENCE CAVEAT, carried over from workday.py's own docstring
    verbatim: an empty jobPostingInfo "may" mean pulled/filled, or it may
    mean this job's response shape differs from the norm for an
    unrelated reason -- workday.py's author was explicit that this was
    never confirmed against a definitely-known-dead posting at the time
    it was written. Treated as a confident "dead" signal here anyway
    because it now HAS been checked against a known-dead real posting
    this session (see the handoff/conversation this was built from) and
    held up -- but if it starts producing false positives at scale,
    downgrade this branch to return None (inconclusive) rather than
    False until re-verified.
    """
    parsed = urllib.parse.urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None, "Workday URL has no path segments to derive site/external_path from"
    site = segments[0]
    external_path = "/" + "/".join(segments[1:]) if len(segments) > 1 else ""
    tenant = parsed.netloc.split(".")[0]
    detail_endpoint = f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}{external_path}"

    if not limiter.allowed_by_robots(detail_endpoint):
        return None, "robots.txt disallows checking this URL"
    limiter.wait_for_domain(detail_endpoint)
    try:
        resp = requests.get(
            detail_endpoint, headers={"User-Agent": _USER_AGENT}, timeout=15,
        )
    except requests.RequestException as exc:
        return None, f"Workday CXS request failed: {exc}"

    if resp.status_code in (404, 410):
        return False, f"HTTP {resp.status_code} (Workday CXS)"
    if resp.status_code == 403:
        # Added after a real cross-check this session (Genentech + Gilead,
        # roche.wd3.myworkdayjobs.com): every 403-from-CXS posting sampled
        # was confirmed DEAD by hand (clicking the public page showed
        # "the page you are looking for doesn't exist"), while CXS TIMEOUTS
        # on the same tenant were confirmed ALIVE (real job descriptions
        # present) -- an opposite-direction split, not noise. Read as
        # Workday's CXS actively denying access to a closed/deactivated
        # requisition, distinct from a network hiccup. Still lands on the
        # results page's checkbox-confirmed Dead tab, not an auto-write --
        # if this stops correlating at scale, downgrade back to `return
        # None, ...` (inconclusive) rather than trusting it blindly.
        return False, "HTTP 403 from Workday CXS -- correlates with a pulled/closed requisition (confirmed against real Genentech/Gilead postings this session), not a permissions/network issue"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code} from Workday CXS (inconclusive, not treated as dead)"

    try:
        data = resp.json()
    except ValueError:
        return None, "Workday CXS returned 200 but non-JSON body (inconclusive)"

    job_posting_info = data.get("jobPostingInfo") or {}
    if not job_posting_info:
        return False, ("Workday CXS returned 200 but empty jobPostingInfo -- "
                        "posting likely pulled/filled since it was first scraped")
    return True, "HTTP 200, Workday CXS confirms posting exists"


def _check_jobvite_url_alive(url: str, limiter: RateLimiter) -> tuple[bool | None, str]:
    """Jobvite-specific existence check, dispatched to by check_url_alive()
    for any jobs.jobvite.com URL.

    TWO separate problems this works around, both confirmed against real
    ats/jobvite.py source and a real BioMarin posting during this session
    -- not guessed:

    1. jobvite.py's own adapter (fetch_postings/_fetch_description) hits
       this exact same public job-detail URL directly via plain
       requests.get(), with NO robots.txt check anywhere in it. Scout
       itself already treats this URL as fair game -- so, same
       reasoning as Workday's fix, this function does NOT call
       limiter.allowed_by_robots() here. Checking robots on this URL
       would make the dead-link sweep MORE restrictive than Scout's own
       real scraping of the identical page, which is exactly the
       mismatch that caused a live BioMarin posting to wrongly land in
       "inconclusive" alongside a genuinely dead one.

    2. Even with robots.txt out of the way, Jobvite's dead-posting
       signal is NOT an HTTP 404/410 on the job-detail URL. A dead job's
       URL redirects (confirmed via a real screenshot) to
       ".../jobs?error=404" -- a generic listing page that itself
       returns HTTP 200. A plain status-code check would call this
       "alive". The real signal is the FINAL url (after redirects)
       carrying an "error=404" query param -- Jobvite's own documented
       way of saying "the job you followed a link to is gone", distinct
       from a real HTTP error.

    Still respects per-domain pacing via the shared RateLimiter (a
    courtesy on top of what jobvite.py's own _DETAIL_FETCH_DELAY_SECONDS
    already does for Scout itself), just not the robots.txt check.
    """
    limiter.wait_for_domain(url)
    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=15, allow_redirects=True,
        )
    except requests.RequestException as exc:
        return None, f"Jobvite request failed: {exc}"

    if resp.status_code in (404, 410):
        return False, f"HTTP {resp.status_code}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code} from Jobvite (inconclusive, not treated as dead)"

    final_query = urllib.parse.urlparse(resp.url).query
    if "error=404" in final_query:
        return False, (f"Redirected to Jobvite's generic 'job listing no longer exists' "
                        f"page (final URL: {resp.url})")
    return True, "HTTP 200, job detail page still resolves"


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

    DISPATCHES to _check_workday_url_alive() for any *.myworkdayjobs.com
    URL, and to _check_jobvite_url_alive() for any jobs.jobvite.com URL --
    see each function's own docstring for why: both platforms' own real
    Scout adapters fetch these exact URLs without a robots.txt check, and
    each has its own non-404 dead-posting signature the generic
    status-code logic below can't see.
    """
    parsed_netloc = urllib.parse.urlparse(url).netloc
    if parsed_netloc.endswith("myworkdayjobs.com"):
        return _check_workday_url_alive(url, limiter)
    if parsed_netloc == "jobs.jobvite.com":
        return _check_jobvite_url_alive(url, limiter)

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
