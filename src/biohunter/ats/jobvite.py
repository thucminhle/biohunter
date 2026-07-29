from __future__ import annotations

import urllib.parse

import requests
from bs4 import BeautifulSoup

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"


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

            postings.append(RawPosting(title=title, url=job_url, location=location))

        return postings
