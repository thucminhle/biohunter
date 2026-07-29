from __future__ import annotations

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"
_PAGE_SIZE = 20


class WorkdayAdapter(ATSAdapter):
    """Workday doesn't publish a documented public API the way Greenhouse/
    Lever/Ashby do, but every Workday careers site calls an internal JSON
    endpoint (CXS) to render its own search results, and that endpoint
    returns clean JSON with no auth needed. This adapter calls the same
    endpoint the browser does.

    Because this is unofficial and undocumented, Workday could change its
    response shape without notice -- more than the other three adapters,
    treat failures here as "check `run_scout`'s error message before
    assuming your company config is wrong."

    ats_slug format: "{subdomain}/{site}", where `subdomain` is the part of
    the careers URL before `.myworkdayjobs.com` (e.g. "roche.wd3") and
    `site` is the tenant's job-board name (e.g. "ROG-A2O-GENE"). Both come
    straight out of the company's existing Workday URL:
        https://roche.wd3.myworkdayjobs.com/ROG-A2O-GENE
                └────┬────┘                 └────┬────┘
                 subdomain                      site

    Some companies (e.g. Denali Therapeutics) run SEVERAL separate Workday
    career sites under one tenant rather than a single unified one -- e.g.
    dnli.wd1.myworkdayjobs.com/Discovery, /Development, /Corporate_Positions,
    /Internships all exist independently. For these, comma-separate the
    site names:
        ats_slug: "dnli.wd1/Discovery,Development,Corporate_Positions"
    Postings from all listed sites are combined into one result set.
    """

    name = "workday"

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        subdomain, _, sites_raw = ats_slug.partition("/")
        if not subdomain or not sites_raw:
            raise ValueError(
                f"workday ats_slug must be '{{subdomain}}/{{site}}[,{{site2}},...]', got: {ats_slug!r}"
            )
        tenant = subdomain.split(".")[0]
        host = f"{subdomain}.myworkdayjobs.com"

        postings: list[RawPosting] = []
        for site in [s.strip() for s in sites_raw.split(",") if s.strip()]:
            postings.extend(self._fetch_one_site(host, tenant, site))
        return postings

    def _fetch_one_site(self, host: str, tenant: str, site: str) -> list[RawPosting]:
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        postings: list[RawPosting] = []
        offset = 0
        while True:
            resp = requests.post(
                endpoint,
                json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
                headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            job_postings = data.get("jobPostings", [])
            if not job_postings:
                break

            for job in job_postings:
                external_path = job.get("externalPath", "")
                postings.append(
                    RawPosting(
                        title=job.get("title", "").strip(),
                        url=f"https://{host}/{site}{external_path}",
                        location=job.get("locationsText"),
                    )
                )

            offset += _PAGE_SIZE
            total = data.get("total", 0)
            if offset >= total:
                break

        return postings
