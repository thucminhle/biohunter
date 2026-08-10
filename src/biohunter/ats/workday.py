from __future__ import annotations

import logging
import time

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"
_PAGE_SIZE = 20

# Polite delay between per-job description detail calls (see
# _fetch_description() below) -- this adapter now makes one extra HTTP
# round trip PER JOB, on top of the existing list-page calls, against an
# undocumented endpoint. A larger tenant (Genentech: 253 postings) means
# 253 extra requests per Scout run. Scoped as a plain sleep INSIDE this
# adapter rather than threading the existing RateLimiter through
# ATSAdapter.fetch_postings()'s signature -- that would mean changing
# base.py's abstract method and every other adapter file for a need that,
# so far, is Workday-specific (Greenhouse/Lever/Ashby/Jobsyn all return
# full description in their one list/search call already). Revisit if a
# second adapter ever needs the same per-job-detail-call shape.
_DETAIL_FETCH_DELAY_SECONDS = 0.3

logger = logging.getLogger(__name__)


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

    DESCRIPTION FETCH (added 2026-08-09, after `biohunter score-postings`
    ran against real data and found every Workday-sourced posting had
    description=NULL): the list/search endpoint used below (`/jobs`) only
    ever returns title/location/URL -- it has no description field at
    all, unlike Greenhouse/Lever/Ashby/Jobsyn's equivalents. Getting the
    actual job description requires a SECOND call, per job, to a detail
    endpoint. The shape used here --
        GET https://{host}/wday/cxs/{tenant}/{site}{external_path}
    (mirroring exactly how this adapter already builds the public-facing
    apply URL, just with a /wday/cxs/{tenant}/{site} prefix instead of
    /{site}) -- is the commonly-observed Workday CXS convention, NOT
    something confirmed against your specific tenants. Test against one
    real posting with --debug before trusting this at scale; if a
    tenant's response shape differs, _fetch_description() is written to
    fail soft (logs a warning, returns None, does NOT abort the rest of
    that company's fetch) rather than take down the whole run.
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
                description = self._fetch_description(host, tenant, site, external_path)
                postings.append(
                    RawPosting(
                        title=job.get("title", "").strip(),
                        url=f"https://{host}/{site}{external_path}",
                        location=job.get("locationsText"),
                        description=description,
                    )
                )

            offset += _PAGE_SIZE
            total = data.get("total", 0)
            if offset >= total:
                break

        return postings

    def _fetch_description(self, host: str, tenant: str, site: str, external_path: str) -> str | None:
        """One extra GET per job -- see class docstring's DESCRIPTION
        FETCH note for the endpoint-shape caveat. Returns raw text (HTML
        or plain, whichever Workday sends) -- detector.py's
        _clean_description() already runs centrally over every ATS
        adapter's output in _upsert_postings(), so this deliberately does
        NOT clean/parse anything here, just returns whatever the field
        holds, same contract every other adapter's description follows.

        Fails soft: any request/parse error logs a warning and returns
        None rather than raising, so one bad detail-fetch (a job that's
        been pulled, a malformed response, a timeout) never aborts the
        rest of this company's Scout pass -- run_scout's per-company
        try/except would otherwise treat that as a total failure for
        every posting in the same page, not just the one job.
        """
        if not external_path:
            return None

        detail_endpoint = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
        try:
            resp = requests.get(
                detail_endpoint,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            description = data.get("jobPostingInfo", {}).get("jobDescription")

            # DISTINCT from the except block below: this is a response that
            # succeeded (200, valid JSON) but simply doesn't carry a
            # description -- e.g. a posting that's been pulled/filled
            # between the list call and this detail call, or a job-type
            # variant with a different response shape. Silently returning
            # None here (as this did before 2026-08-10) looks identical in
            # the DB to a request that failed outright, but it's a
            # different failure mode with a different fix -- worth its own
            # warning so a future "why are 30% of these missing, with zero
            # logged failures" question doesn't have to be re-diagnosed
            # from scratch the way this one did.
            if not description:
                logger.warning(
                    "[workday] %s returned 200 but no jobPostingInfo.jobDescription -- "
                    "posting may have been pulled/filled since the list call, or this "
                    "job's response shape differs from the norm. Raw jobPostingInfo keys: %s",
                    detail_endpoint, list(data.get("jobPostingInfo", {}).keys()),
                )
            return description
        except Exception as exc:  # noqa: BLE001 -- see docstring: fail soft, one bad
            # job's detail call must never sink the rest of this company's fetch.
            logger.warning(
                "[workday] description fetch failed for %s -- leaving description "
                "unset for this posting (title/location/URL are unaffected): %s",
                detail_endpoint, exc,
            )
            return None
        finally:
            time.sleep(_DETAIL_FETCH_DELAY_SECONDS)
