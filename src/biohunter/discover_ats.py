"""
discover_ats.py -- headless-browser ATS discovery for JS-rendered career pages.

Per ADR-0003 and docs/ROADMAP.md's Scout & ingestion subsystem (step 2 of
the guided company onboarding chain): detect_ats.py's plain requests.get()
fingerprint scan only ever sees whatever ships in the *initial* HTML
response. Companies whose careers page renders its ATS iframe/link via
client-side JS -- confirmed real cases this project has already hit:
Scribe Therapeutics (scribetx.com/careers -- Webflow CMS, empty
placeholder in static HTML) and Astellas (astellascareers.jobs --
NLX-backed, same client-render problem) -- never show a fingerprint to
detect_ats.py at all, regardless of whether they're actually running a
known ATS underneath.

This module re-runs the SAME fingerprint patterns detect_ats.py already
defines (imported from there, not duplicated) against a page that's been
given a real headless-Chromium render first, plus every XHR/fetch
response URL observed while that render happened -- catching cases where
the fingerprint only ever appears in a background network call, not the
final DOM (e.g. an iframe whose src is set by JS after load).

No new dependency: Playwright is already required by resume_pdf.py
(`pip install playwright && playwright install chromium`), and this
module reuses that same installed browser.

USAGE:
    # Default: re-scan every company in config/companies.yaml that
    # detect_ats.py already tried and left with ats_type: null. This is
    # the normal way to run this -- it picks up exactly where
    # detect_ats.py left off, no extra config needed.
    python -m biohunter.discover_ats

    # Or, same shape as detect_ats.py, scan a fresh input batch instead:
    python -m biohunter.discover_ats --input config/companies_input.yaml

Companies that still don't match ANY known ATS after a real render are
printed with every likely-JSON XHR/fetch endpoint seen during page load
-- this is exactly the DevTools Network-tab list a human would need to
hand-build the next stage (the guided extraction wizard, not yet built),
given for free since the browser already rendered the page once here.
These diagnostics are console-only -- never written into companies.yaml,
which keeps the same shape it already has (see main()).

DELIBERATE DIVERGENCE from detect_ats.py, named explicitly rather than
left implicit: this module DOES check robots.txt before rendering, where
detect_ats.py's plain GET currently does not. A full headless render
(loading every sub-resource a real browser would) is a meaningfully
heavier request than one GET, so it gets the more cautious check.
detect_ats.py itself is unchanged -- worth revisiting there separately if
it matters, not fixed here.

KNOWN LIMITATION, not solved here: this does not attempt scroll-triggered
or click-triggered lazy loading (e.g. a "Load more jobs" button that only
fires its own XHR on click). If a company's fingerprint still isn't
visible after one real render + networkidle wait, it falls through to
manual review the same as it does today. Worth revisiting if that turns
out to be a common case, not assumed to be one yet.
"""
from __future__ import annotations

import argparse
import pathlib

import yaml
from playwright.sync_api import Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .detect_ats import _COMPANIES_YAML, _PATTERNS, load_existing
from .scout.ratelimit import RateLimiter, _USER_AGENT

_DEFAULT_TIMEOUT_MS = 30_000
_JSON_LIKE_CONTENT_TYPES = ("application/json", "text/json")


def _capture_candidate_endpoints(responses: list[Response]) -> list[str]:
    """Every XHR/fetch response that looks like it might carry job data,
    filtered to JSON-ish content types so a human isn't handed every font/
    CSS/analytics request the page happened to make along the way."""
    seen: set[str] = set()
    candidates: list[str] = []
    for resp in responses:
        try:
            if resp.request.resource_type not in ("xhr", "fetch"):
                continue
            content_type = resp.headers.get("content-type", "")
        except Exception:  # noqa: BLE001 -- a response object can outlive its page/context
            continue
        if not any(ct in content_type for ct in _JSON_LIKE_CONTENT_TYPES):
            continue
        if resp.url in seen:
            continue
        seen.add(resp.url)
        candidates.append(resp.url)
    return candidates


def discover_one(
    name: str,
    careers_url: str,
    limiter: RateLimiter,
    browser,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> dict:
    """Same return shape as detect_ats.py's detect_one(), plus an optional
    `_candidate_endpoints` list on a manual-review result -- console-only
    diagnostic, stripped before anything is written to companies.yaml (see
    main())."""
    result = {"name": name, "careers_url": careers_url, "ats_type": None}

    if not limiter.allowed_by_robots(careers_url):
        result["_detect_error"] = "robots.txt disallows fetching this URL"
        return result
    limiter.wait_for_domain(careers_url)

    responses: list[Response] = []
    page = browser.new_page(user_agent=_USER_AGENT)
    # NOTE: must be a real Python function/lambda, not responses.append
    # directly -- Playwright's event wrapper does setattr() on the handler
    # to tag it internally, which fails on a bound builtin method
    # (list.append) with "'builtin_function_or_method' object has no
    # attribute '_pw_impl_instance_'". Confirmed against a real error this
    # session, not a hypothetical.
    page.on("response", lambda resp: responses.append(resp))
    try:
        page.goto(careers_url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            # Some SPAs never go fully idle (polling/analytics beacons) --
            # not fatal, we already have whatever rendered by that point.
            pass
        html = page.content()
        final_url = page.url
    except PlaywrightTimeoutError as exc:
        result["_detect_error"] = f"page load timed out: {exc}"
        page.close()
        return result
    except Exception as exc:  # noqa: BLE001
        result["_detect_error"] = str(exc)
        page.close()
        return result

    endpoint_urls = "\n".join(r.url for r in responses)
    search_space = final_url + "\n" + html + "\n" + endpoint_urls

    for ats_type, pattern in _PATTERNS:
        match = pattern.search(search_space)
        if not match:
            continue
        result["ats_type"] = ats_type
        if ats_type == "workday":
            subdomain, site = match.group(1), match.group(2)
            result["ats_slug"] = f"{subdomain}/{site}"
            result["careers_url"] = f"https://{subdomain}.myworkdayjobs.com/{site}"
        else:
            result["ats_slug"] = match.group(1)
        page.close()
        return result

    result["_needs_manual_review"] = True
    result["_candidate_endpoints"] = _capture_candidate_endpoints(responses)
    page.close()
    return result


def _pending_from_companies_yaml() -> list[dict]:
    """Default input source: every company already in companies.yaml with
    ats_type still null -- i.e. whatever detect_ats.py's static scan
    already tried and couldn't fingerprint. Matches this module's role as
    step 2 in the chain, not a fresh batch scan."""
    existing = load_existing()
    return [
        {"name": c["name"], "careers_url": c["careers_url"]}
        for c in existing.values()
        if not c.get("ats_type")
    ]


def load_input(path: pathlib.Path) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("companies", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=None,
        help="Path to a companies-list YAML (name + careers_url only). "
        "Default: re-scan companies.yaml entries that still have ats_type: null.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-detect even companies that already have ats_type set"
    )
    parser.add_argument(
        "--timeout", type=int, default=_DEFAULT_TIMEOUT_MS, help="Per-company page-load timeout, in ms"
    )
    parser.add_argument(
        "--headful", action="store_true", help="Show the browser window instead of running headless (debugging)"
    )
    args = parser.parse_args()

    to_check = load_input(pathlib.Path(args.input)) if args.input else _pending_from_companies_yaml()
    if not to_check:
        print("Nothing to check: no companies.yaml entries with ats_type: null, and no --input given.")
        return

    existing = load_existing()
    limiter = RateLimiter()

    final: list[dict] = []
    detected, needs_review, errored = 0, 0, 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        try:
            for entry in to_check:
                name = entry["name"]
                prior = existing.get(name)
                if prior and prior.get("ats_type") and not args.force:
                    print(f"  [skip] {name}: already configured (ats_type={prior['ats_type']})")
                    final.append(prior)
                    continue

                result = discover_one(name, entry["careers_url"], limiter, browser, timeout_ms=args.timeout)

                if result.get("_detect_error"):
                    print(f"  [ERROR] {name}: {result['_detect_error']}")
                    errored += 1
                    # Preserve whatever was already configured (e.g. a
                    # hand-set css_selector for a known fallback-scrape
                    # company) rather than overwriting it with a bare
                    # error record.
                    final.append(prior if prior else {"name": name, "careers_url": entry["careers_url"], "ats_type": None})
                    continue

                if result.get("ats_type"):
                    print(f"  [ok] {name}: {result['ats_type']} (ats_slug={result['ats_slug']}) -- found via headless render")
                    detected += 1
                    result.pop("_needs_manual_review", None)
                    result.pop("_candidate_endpoints", None)
                    final.append(result)
                    continue

                print(f"  [manual] {name}: no ATS fingerprint found even after a real render")
                endpoints = result.get("_candidate_endpoints") or []
                if endpoints:
                    print(f"           {len(endpoints)} JSON-ish XHR/fetch endpoint(s) seen -- start here for the wizard:")
                    for url in endpoints[:10]:
                        print(f"             {url}")
                    if len(endpoints) > 10:
                        print(f"             ... and {len(endpoints) - 10} more")
                needs_review += 1
                # Same reasoning as the error case above: don't clobber a
                # prior hand-configured entry (e.g. an existing
                # css_selector) with a bare "still nothing" record.
                final.append(prior if prior else {"name": name, "careers_url": entry["careers_url"], "ats_type": None})
        finally:
            browser.close()

    # Preserve any existing companies not present in this batch.
    checked_names = {e["name"] for e in to_check}
    for name, prior in existing.items():
        if name not in checked_names:
            final.append(prior)

    output = {"companies": final}
    header = (
        "# Auto-generated/merged by detect_ats.py + discover_ats.py -- hand-edit\n"
        "# css_selector for any company marked 'manual' above.\n"
    )
    _COMPANIES_YAML.write_text(header + yaml.safe_dump(output, sort_keys=False, default_flow_style=False))

    print(
        f"\nDone: {detected} auto-detected via headless render, {needs_review} still need "
        f"the manual wizard, {errored} failed to load. Written to {_COMPANIES_YAML}"
    )


if __name__ == "__main__":
    main()
