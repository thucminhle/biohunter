from __future__ import annotations

import logging

import requests

from .base import ATSAdapter, RawPosting

_USER_AGENT = "BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)"
_SEARCH_URL = "https://prod-search-api.jobsyn.org/api/v1/solr/search"
_PAGE_SIZE = 50

logger = logging.getLogger(__name__)


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
    and `location-slug` is derived by lowercasing/dehyphenating a
    location string: `location_exact` when present (the normal case for
    domestic/US postings), otherwise `city_exact` + `country_short_exact`
    combined (confirmed 2026-08-13 against a real international posting
    -- some postings, mostly international, lack location_exact entirely,
    and using bare city_exact alone silently produced a wrong, 404ing
    URL with no warning). If even that can't be built, falls back to the
    bare careers-root URL and logs a warning.
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

        # REAL FIX (2026-08-13, from actual API + browser-confirmed URL
        # data): location_exact IS present for domestic (US) postings, and
        # using it directly was already correct -- confirmed against a real
        # Arlington, TX posting, whose URL matched this construction byte
        # for byte. The actual bug was in the fallback: international
        # postings often have NO location_exact, only city_exact (e.g.
        # "Bengaluru" with no state/country attached). The OLD code fell
        # back to bare city_exact alone, which produced a URL that LOOKED
        # valid (no warning logged, no fallback-to-/jobs/ triggered) but
        # was actually wrong and would 404 -- worse than the logged
        # fallback case, because nothing flagged it. Confirmed via a real
        # Bengaluru posting: the site's real URL uses "bengaluru-ind"
        # (city + country_short_exact), not "bengaluru" alone.
        location_exact = job.get("location_exact")
        city_exact = job.get("city_exact")
        country_short_exact = job.get("country_short_exact")

        if location_exact:
            location = location_exact
        elif city_exact and country_short_exact:
            location = f"{city_exact}, {country_short_exact}"
        else:
            # Still missing what's needed for a correct slug (e.g. city
            # with no country at all) -- this is the genuinely-unbuildable
            # case the fallback-to-/jobs/ path below is for.
            location = city_exact

        title_slug = job.get("title_slug")
        guid = job.get("guid")
        if location and title_slug and guid:
            location_slug = location.lower().replace(",", "").replace(" ", "-")
            url = f"{origin}/{location_slug}/{title_slug}/{guid}/job/"
        else:
            # Missing a piece needed to build the exact URL. Fall back to
            # the careers site root rather than guess wrong.
            #
            # Logs which piece was missing and for which job -- fail-soft
            # but loud, same spirit as workday.py's own detail-fetch
            # warning. scraper.py's check_url_alive() also flags any URL
            # with path exactly "/jobs/" as inconclusive rather than
            # always-"alive", so this warning is the thing that tells you
            # WHY a given posting ended up with that meaningless URL.
            missing = [name for name, val in (
                ("location_exact/city_exact(+country)", location),
                ("title_slug", title_slug),
                ("guid", guid),
            ) if not val]
            logger.warning(
                "[jobsyn] falling back to bare careers-root URL for %r -- "
                "missing %s in the API response. This posting's URL won't "
                "point at its own detail page.",
                title or guid, missing,
            )
            url = f"{origin}/jobs/"

        return RawPosting(title=title, url=url, location=location, description=job.get("description"))
