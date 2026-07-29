from __future__ import annotations

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"
_SEARCH_URL = "https://prod-search-api.jobsyn.org/api/v1/solr/search"
_PAGE_SIZE = 50


class JobsynAdapter(ATSAdapter):
    """DirectEmployers' National Labor Exchange (jobsyn.org) backend --
    common among federal-contractor employers (OFCCP compliance postings;
    look for `"federal_contractor": true` in the job data), often paired
    with an NLX-branded career site skin like Astellas's.

    Unlike every other adapter here, this backend is company-scoped by
    HTTP headers (Origin/Referer/X-Origin set to the career site's own
    domain), NOT by anything in the URL or query string -- the same
    endpoint serves many different companies' career sites depending on
    which domain claims to be asking.

    ats_slug is just that domain, e.g. "astellascareers.jobs".

    Job posting URLs follow the pattern:
        https://{domain}/{location-slug}/{title_slug}/{guid}/job/
    where `title_slug` and `guid` come directly from the API response,
    and `location-slug` is derived by lowercasing/dehyphenating
    `location_exact` (falls back to `city_exact`, then to the bare
    careers URL if neither is present -- some international postings
    lack `location_exact` entirely).
    """

    name = "jobsyn"

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        domain = ats_slug
        origin = f"https://{domain}"
        headers = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
            "Origin": origin,
            "Referer": origin + "/",
            "X-Origin": domain,
        }

        postings: list[RawPosting] = []
        page = 1
        while True:
            resp = requests.get(
                _SEARCH_URL,
                params={"page": page, "num_items": _PAGE_SIZE},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for job in data.get("jobs", []):
                postings.append(self._to_raw_posting(job, origin))

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_pages"):
                break
            page += 1

        return postings

    @staticmethod
    def _to_raw_posting(job: dict, origin: str) -> RawPosting:
        title = job.get("title_exact", "").strip()
        location = job.get("location_exact") or job.get("city_exact")

        title_slug = job.get("title_slug")
        guid = job.get("guid")
        if location and title_slug and guid:
            location_slug = location.lower().replace(",", "").replace(" ", "-")
            url = f"{origin}/{location_slug}/{title_slug}/{guid}/job/"
        else:
            # Missing a piece needed to build the exact URL (happens for
            # some international postings without location_exact) --
            # fall back to the careers site root rather than guess wrong.
            url = f"{origin}/jobs/"

        return RawPosting(title=title, url=url, location=location, description=job.get("description"))
