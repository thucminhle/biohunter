from __future__ import annotations

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"


class GreenhouseAdapter(ATSAdapter):
    name = "greenhouse"

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{ats_slug}/jobs?content=true"
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        postings = []
        for job in data.get("jobs", []):
            location = None
            loc_obj = job.get("location") or {}
            if isinstance(loc_obj, dict):
                location = loc_obj.get("name")

            postings.append(
                RawPosting(
                    title=job.get("title", "").strip(),
                    url=job.get("absolute_url", ""),
                    location=location,
                    description=job.get("content"),  # HTML; caller may strip tags
                )
            )
        return postings
