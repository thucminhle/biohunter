"""
custom_api.py -- one reviewed ATSAdapter that interprets a per-company
field-mapping CONFIG at runtime, rather than one generated adapter class
per company.

Per docs/ROADMAP.md's Scout & ingestion subsystem: for companies whose
career site runs a JSON search API that isn't one of the six known
platforms (Greenhouse/Lever/Ashby/Workday/Jobvite/jobsyn), the guided
onboarding wizard (not yet built) will let an LLM propose a field mapping
-- which JSON keys are title/location/description/url -- from a real
sample response the user pastes in from DevTools. What gets saved is
that mapping (data, in config/custom_apis.yaml), never freshly generated
Python. This module is the one hand-written interpreter for all of those
mappings.

Real example this schema was designed against: this session's
discover_ats.py run found Astellas' real search API at
https://prod-search-api.jobsyn.org/api/v1/solr/search?page=1&num_items=10
-- confirmed to exist, but its response body was never actually fetched
or inspected this session. The sample custom_apis.yaml entry at the
bottom of this file's docstring uses that real URL with CLEARLY-MARKED
placeholder field names -- do not treat those field names as real without
checking an actual response first.

ARCHITECTURAL NOTE, worth re-stating since it's easy to miss: unlike the
six REGISTRY adapters (ashby.py, greenhouse.py, etc.), which are stateless
singletons parametrized only by a short `ats_slug` at call time (because
every company on e.g. Greenhouse shares the same URL template),
CustomAPIAdapter can't work that way -- every company's URL, pagination,
and field names are completely different, not just a slug substitution.
So it is NOT added to ats/__init__.py's REGISTRY dict. Building one
requires a full CustomAPIConfig at construction time (see
load_custom_api_config()), one instance per company. Wiring "if a
company's ats_type is custom_api, build one of these instead of a
REGISTRY lookup" into Scout's actual per-company dispatch loop is a
follow-up step -- it needs scout/__init__.py, which hasn't been uploaded
in this session, so it isn't touched here.

---
Example config/custom_apis.yaml entry (illustrative field names, marked
as such -- the real ones need to come from an actual inspected response):

    Astellas:
      method: GET
      url: "https://prod-search-api.jobsyn.org/api/v1/solr/search"
      query_params:
        num_items: 50
      pagination:
        type: page_number
        param: page
        start_page: 1
        max_pages: 20
      list_path: "response.docs"        # PLACEHOLDER -- verify against a real response
      fields:
        title: "job_title"               # PLACEHOLDER
        url_template: "https://astellascareers.jobs/job/{raw.job_id}"  # PLACEHOLDER
        location: "job_location"         # PLACEHOLDER
        description: "job_description"   # PLACEHOLDER
"""
from __future__ import annotations

import dataclasses
import pathlib
import re

import requests
import yaml

from .base import ATSAdapter, RawPosting
from ..scout.ratelimit import RateLimiter, _USER_AGENT

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_CUSTOM_APIS_YAML = _REPO_ROOT / "config" / "custom_apis.yaml"

_PLACEHOLDER_PATTERN = re.compile(r"\{([^}]+)\}")


def _resolve_path(obj, dotted_path: str):
    """Walk a dotted path like 'location.city' or 'response.docs' through
    a nested dict/list JSON structure. Returns None if any segment is
    missing or of the wrong shape, rather than raising -- a real API's
    per-item JSON is often inconsistent (e.g. some postings missing a
    field entirely), and callers decide whether a None matters."""
    if not dotted_path:
        return obj
    current = obj
    for segment in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _render_url_template(template: str, item: dict) -> str | None:
    """Resolves `{raw.<dot.path>}` placeholders in a URL template against
    the raw item JSON, e.g. 'https://x.com/job/{raw.id}'. Returns None if
    any referenced path is missing or malformed, so the caller can raise a
    clear error instead of silently emitting a URL with a literal
    '{raw.id}' still in it."""
    missing = False

    def _sub(match: re.Match) -> str:
        nonlocal missing
        placeholder = match.group(1)
        if not placeholder.startswith("raw."):
            missing = True
            return ""
        value = _resolve_path(item, placeholder[len("raw."):])
        if value is None:
            missing = True
            return ""
        return str(value)

    rendered = _PLACEHOLDER_PATTERN.sub(_sub, template)
    return None if missing else rendered


@dataclasses.dataclass
class FieldMap:
    """Which JSON key (dot-path) inside each posting-item object maps to
    each RawPosting field. Exactly one of `url` / `url_template` must be
    set -- `url` for a direct field, `url_template` for building a URL
    out of other fields (e.g. an id) via {raw.<path>} placeholders."""
    title: str
    url: str | None = None
    url_template: str | None = None
    location: str | None = None
    description: str | None = None


@dataclasses.dataclass
class PaginationConfig:
    type: str = "none"  # "none" | "page_number"
    param: str = "page"
    start_page: int = 1
    max_pages: int = 20  # safety cap -- never fetch unbounded pages on a misconfigured/broken API


@dataclasses.dataclass
class CustomAPIConfig:
    company_name: str
    method: str  # "GET" | "POST"
    url: str
    fields: FieldMap
    query_params: dict = dataclasses.field(default_factory=dict)
    json_body: dict | None = None  # request body, for POST-based search APIs
    pagination: PaginationConfig = dataclasses.field(default_factory=PaginationConfig)
    list_path: str = ""  # dot-path to the array of posting-item objects; "" means the response body IS the array


def load_custom_api_config(company_name: str, path: pathlib.Path = _CUSTOM_APIS_YAML) -> CustomAPIConfig:
    """Loads one company's mapping config from config/custom_apis.yaml.

    Raises ValueError with a specific, actionable message on any missing
    or invalid required key. These configs are meant to be produced by an
    LLM-assisted wizard (not yet built) and hand-approved by a human
    before saving -- failing loudly and specifically here, rather than
    guessing a default, matters more than it would for hand-written code,
    since a silently-wrong mapping would just produce silently-wrong
    postings downstream.
    """
    if not path.exists():
        raise ValueError(f"No custom API config file found at {path}")
    data = yaml.safe_load(path.read_text()) or {}
    entry = data.get(company_name)
    if entry is None:
        raise ValueError(f"No custom_apis.yaml entry found for company {company_name!r}")

    def _require(d: dict, key: str, context: str):
        if key not in d or d[key] in (None, ""):
            raise ValueError(f"custom_apis.yaml[{company_name!r}]{context}: missing required key {key!r}")
        return d[key]

    fields_raw = _require(entry, "fields", "")
    title_path = _require(fields_raw, "title", ".fields")
    has_url = bool(fields_raw.get("url"))
    has_url_template = bool(fields_raw.get("url_template"))
    if has_url == has_url_template:  # both set, or neither set -- both are ambiguous/invalid
        raise ValueError(
            f"custom_apis.yaml[{company_name!r}].fields: needs EXACTLY ONE of 'url' or 'url_template', "
            f"not both and not neither"
        )

    field_map = FieldMap(
        title=title_path,
        url=fields_raw.get("url"),
        url_template=fields_raw.get("url_template"),
        location=fields_raw.get("location"),
        description=fields_raw.get("description"),
    )

    pagination_raw = entry.get("pagination", {}) or {}
    pagination = PaginationConfig(
        type=pagination_raw.get("type", "none"),
        param=pagination_raw.get("param", "page"),
        start_page=pagination_raw.get("start_page", 1),
        max_pages=pagination_raw.get("max_pages", 20),
    )
    if pagination.type not in ("none", "page_number"):
        raise ValueError(
            f"custom_apis.yaml[{company_name!r}].pagination.type: unsupported value {pagination.type!r} "
            f"(must be 'none' or 'page_number')"
        )

    method = str(entry.get("method", "GET")).upper()
    if method not in ("GET", "POST"):
        raise ValueError(f"custom_apis.yaml[{company_name!r}].method: unsupported value {method!r} (must be GET or POST)")

    return CustomAPIConfig(
        company_name=company_name,
        method=method,
        url=_require(entry, "url", ""),
        fields=field_map,
        query_params=entry.get("query_params", {}) or {},
        json_body=entry.get("json_body"),
        pagination=pagination,
        list_path=entry.get("list_path", ""),
    )


class CustomAPIAdapter(ATSAdapter):
    """One reviewed adapter, driven entirely by a CustomAPIConfig bound at
    construction time -- see this module's docstring for why it can't be
    a REGISTRY singleton like the six built-in platform adapters."""

    name = "custom_api"

    def __init__(self, config: CustomAPIConfig, limiter: RateLimiter | None = None):
        self.config = config
        self._limiter = limiter or RateLimiter()

    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        """`ats_slug` is accepted only to satisfy ATSAdapter's shared
        abstract signature -- functionally ignored, since this adapter's
        real per-company request/response shape is bound at __init__ time
        via CustomAPIConfig, not passed per-call the way the six REGISTRY
        adapters take a short platform slug. Raises requests.HTTPError /
        requests.ConnectionError on a fetch failure and ValueError on a
        response that doesn't match the configured mapping -- both
        propagate uncaught, same contract as every other ATSAdapter (see
        base.py): Scout is responsible for retry/backoff and
        stall-flagging, not this method.
        """
        cfg = self.config
        postings: list[RawPosting] = []
        page = cfg.pagination.start_page if cfg.pagination.type == "page_number" else None
        pages_fetched = 0

        while True:
            params = dict(cfg.query_params)
            if cfg.pagination.type == "page_number":
                params[cfg.pagination.param] = page

            self._limiter.wait_for_domain(cfg.url)
            headers = {"User-Agent": _USER_AGENT}
            if cfg.method == "GET":
                resp = requests.get(cfg.url, params=params, headers=headers, timeout=15)
            else:  # "POST" -- validated in load_custom_api_config(), nothing else reaches here
                resp = requests.post(cfg.url, params=params, json=cfg.json_body, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            items = _resolve_path(data, cfg.list_path)
            if items is None:
                items = []
            if not isinstance(items, list):
                raise ValueError(
                    f"CustomAPIAdapter for {cfg.company_name}: list_path {cfg.list_path!r} did not "
                    f"resolve to a list (got {type(items).__name__}) -- check the mapping config against "
                    f"a real response"
                )

            if not items:
                break  # no more results this page (or, for pagination.type == 'none', the one response)

            for item in items:
                postings.append(self._item_to_posting(item))

            pages_fetched += 1
            if cfg.pagination.type != "page_number":
                break
            if pages_fetched >= cfg.pagination.max_pages:
                break
            page += 1

        return postings

    def _item_to_posting(self, item: dict) -> RawPosting:
        f = self.config.fields

        title = _resolve_path(item, f.title)
        if title is None:
            raise ValueError(
                f"CustomAPIAdapter for {self.config.company_name}: fields.title path {f.title!r} did not "
                f"resolve on a real posting item. Item keys seen: "
                f"{list(item.keys()) if isinstance(item, dict) else '(item is not a dict)'}"
            )

        if f.url:
            url = _resolve_path(item, f.url)
        else:
            url = _render_url_template(f.url_template, item)
        if url is None:
            raise ValueError(
                f"CustomAPIAdapter for {self.config.company_name}: could not resolve a url for posting "
                f"{title!r} -- check fields.url / fields.url_template against a real response"
            )

        location = _resolve_path(item, f.location) if f.location else None
        description = _resolve_path(item, f.description) if f.description else None

        return RawPosting(
            title=str(title),
            url=str(url),
            location=str(location) if location is not None else None,
            description=str(description) if description is not None else None,
        )
