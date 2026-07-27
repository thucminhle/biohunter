from __future__ import annotations

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"


class AshbyAdapter(ATSAdapter):
    name = "ashby"

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{ats_slug}?includeCompensation=false"
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        postings = []
        for job in data.get("jobs", []):
            postings.append(
                RawPosting(
                    title=job.get("title", "").strip(),
                    url=job.get("jobUrl", ""),
                    location=job.get("location"),
                    description=job.get("descriptionPlain") or job.get("descriptionHtml"),
                )
            )
        return postings
