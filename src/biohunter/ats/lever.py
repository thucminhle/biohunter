from __future__ import annotations

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"


class LeverAdapter(ATSAdapter):
    name = "lever"

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        url = f"https://api.lever.co/v0/postings/{ats_slug}?mode=json"
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        postings = []
        for job in data:
            categories = job.get("categories", {}) or {}
            postings.append(
                RawPosting(
                    title=job.get("text", "").strip(),
                    url=job.get("hostedUrl", ""),
                    location=categories.get("location"),
                    description=job.get("descriptionPlain") or job.get("description"),
                )
            )
        return postings
