from __future__ import annotations

import logging
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"

# Same self-contained-delay reasoning as workday.py's _DETAIL_FETCH_DELAY_SECONDS:
# one extra HTTP GET per job now, against a page that's scraped rather than
# a documented API, so a courtesy delay between per-job fetches, scoped to
# this adapter, rather than threading the existing RateLimiter through
# ATSAdapter.fetch_postings()'s signature.
_DETAIL_FETCH_DELAY_SECONDS = 0.3

# Candidate CSS selectors for the description container on a Jobvite job
# detail page (jobs.jobvite.com/{company}/job/{id}), tried in order, first
# non-trivial match wins. UNVERIFIED against a real page as of this fix --
# Jobvite has no documented API (see class docstring), so this list is a
# best guess at common Jobvite template class/id names, not a confirmed
# selector. If _fetch_description() logs "no selector matched" for your
# real postings, view-source one real job detail page and add/replace the
# matching selector here.
_DESCRIPTION_SELECTORS = [
    "#jv-job-detail-description",
    ".jv-job-detail-description",
    "div.jv-page-body",
    "article",
]

logger = logging.getLogger(__name__)


class JobviteAdapter(ATSAdapter):
    """Unlike Greenhouse/Lever/Ashby, Jobvite doesn't expose a public,
    no-auth JSON API -- their official API requires a customer-issued key.
    However, jobs.jobvite.com/{company}/jobs is a plain server-rendered
    HTML page (confirmed by inspection, not JS-rendered), listing jobs in
    tables grouped by department, with each row containing a link to
    /{company}/job/{id} and a location cell. This adapter scrapes that
    structure directly.

    ats_slug is just the company token, e.g. "biomarin" for
    jobs.jobvite.com/biomarin/jobs.

    DESCRIPTION FETCH (added 2026-08-09, same finding that prompted
    workday.py's equivalent fix -- `biohunter score-postings` run against
    real data found every Jobvite-sourced posting, e.g. BioMarin's 133,
    had description=NULL): the listing page scraped above never contained
    description text -- only title/URL/location per row. Getting the
    actual JD requires a second fetch, per job, of that job's own detail
    page (job_url, already captured per posting), then scraping the
    description out of ITS html. See _DESCRIPTION_SELECTORS above for the
    caveat: this adapter has no documented API to lean on, so the
    selector list is a best guess pending verification against a real
    BioMarin posting.
    """

    name = "jobvite"

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        url = f"https://jobs.jobvite.com/{ats_slug}/jobs"
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        postings: list[RawPosting] = []
        job_url_fragment = f"/{ats_slug}/job/"

        for anchor in soup.find_all("a", href=True):
            if job_url_fragment not in anchor["href"]:
                continue
            title = anchor.get_text(strip=True)
            if not title:
                continue
            job_url = urllib.parse.urljoin(url, anchor["href"])

            # Location is the next table cell in the same row, if this
            # anchor sits inside a <td>/<tr> (the normal layout on Jobvite
            # boards). Falls back to None if the row structure differs.
            location = None
            cell = anchor.find_parent("td")
            if cell is not None:
                row = cell.find_parent("tr")
                if row is not None:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        location = cells[1].get_text(strip=True) or None

            description = self._fetch_description(job_url)
            postings.append(
                RawPosting(title=title, url=job_url, location=location, description=description)
            )

        return postings

    def _fetch_description(self, job_url: str) -> str | None:
        """One extra GET per job, fetching that job's own detail page and
        scraping its description out via _DESCRIPTION_SELECTORS. Returns
        raw HTML text (whatever's inside the matched element) --
        detector.py's _clean_description() already runs centrally over
        every ATS adapter's output in _upsert_postings(), so this
        deliberately does NOT clean/parse anything here, same contract
        every other adapter's description follows.

        Fails soft, same reasoning as workday.py's equivalent: a bad
        detail-page fetch or a selector miss returns None and logs a
        warning rather than raising -- one job's failure must never sink
        the rest of this company's listing scrape.
        """
        try:
            resp = requests.get(job_url, headers={"User-Agent": _USER_AGENT}, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for selector in _DESCRIPTION_SELECTORS:
                match = soup.select_one(selector)
                if match is not None:
                    text = str(match)
                    if len(match.get_text(strip=True)) > 40:  # skip near-empty false-positive matches
                        return text

            logger.warning(
                "[jobvite] no description selector matched %s -- tried %s. "
                "View-source this URL and update _DESCRIPTION_SELECTORS in jobvite.py.",
                job_url, _DESCRIPTION_SELECTORS,
            )
            return None
        except Exception as exc:  # noqa: BLE001 -- fail soft, see docstring
            logger.warning(
                "[jobvite] description fetch failed for %s -- leaving description "
                "unset for this posting (title/location/URL are unaffected): %s",
                job_url, exc,
            )
            return None
        finally:
            time.sleep(_DETAIL_FETCH_DELAY_SECONDS)
