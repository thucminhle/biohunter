"""
Auto-detect ATS type + slug for a list of companies, and write/merge the
result into config/companies.yaml.

Usage:
    python -m biohunter.detect_ats --input config/companies_input.yaml

Input file format (config/companies_input.yaml):
    companies:
      - name: Genentech
        careers_url: "https://careers.gene.com/us/en"
      - name: Some Biotech
        careers_url: "https://somebiotech.com/careers"

For each company:
  1. Fetches careers_url (following redirects).
  2. Scans the *final* URL and the page HTML for Greenhouse/Lever/Ashby/
     Workday fingerprints (many companies embed an ATS board via iframe,
     so the fingerprint often lives in the HTML, not the URL you started
     with -- this is why we search page content, not just the final URL).
  3. Fills in ats_type/ats_slug automatically on a match.
  4. Leaves ats_type blank + adds a TODO comment for manual css_selector
     setup on no match.

Existing entries in companies.yaml that already have an ats_type set are
left untouched, unless --force is passed.
"""
from __future__ import annotations

import argparse
import pathlib
import re

import requests
import yaml

from .scout.ratelimit import RateLimiter, _USER_AGENT

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPANIES_YAML = _REPO_ROOT / "config" / "companies.yaml"

# (ats_type, regex). First capture group(s) become the slug.
# Order matters: check the more specific host-based patterns before anything looser.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Greenhouse has two live front-end domains: the legacy "boards.greenhouse.io"
    # and the newer "job-boards.greenhouse.io" -- both use the same underlying
    # job-board token/slug and the same public JSON API, so one pattern covers both.
    ("greenhouse", re.compile(r"(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([a-zA-Z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)")),
    ("workday", re.compile(r"([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)\.myworkdayjobs\.com/([a-zA-Z0-9_-]+)")),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/([a-zA-Z0-9_-]+)")),
]


def detect_one(name: str, careers_url: str, limiter: RateLimiter) -> dict:
    """Returns a dict shaped like a companies.yaml entry."""
    result = {"name": name, "careers_url": careers_url, "ats_type": None}

    try:
        limiter.wait_for_domain(careers_url)
        resp = requests.get(
            careers_url, headers={"User-Agent": _USER_AGENT}, timeout=15, allow_redirects=True
        )
        resp.raise_for_status()
        search_space = resp.url + "\n" + resp.text
    except Exception as exc:  # noqa: BLE001
        result["_detect_error"] = str(exc)
        return result

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
        return result

    result["_needs_manual_review"] = True
    return result


def load_input(path: pathlib.Path) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("companies", [])


def load_existing() -> dict[str, dict]:
    if not _COMPANIES_YAML.exists():
        return {}
    data = yaml.safe_load(_COMPANIES_YAML.read_text()) or {}
    return {c["name"]: c for c in data.get("companies", [])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to a companies-list YAML (name + careers_url only)")
    parser.add_argument("--force", action="store_true", help="Re-detect even companies that already have ats_type set")
    args = parser.parse_args()

    to_check = load_input(pathlib.Path(args.input))
    existing = load_existing()
    limiter = RateLimiter()

    final: list[dict] = []
    detected, needs_review, errored = 0, 0, 0

    for entry in to_check:
        name = entry["name"]
        prior = existing.get(name)
        if prior and prior.get("ats_type") and not args.force:
            print(f"  [skip] {name}: already configured (ats_type={prior['ats_type']})")
            final.append(prior)
            continue

        result = detect_one(name, entry["careers_url"], limiter)
        if result.get("_detect_error"):
            print(f"  [ERROR] {name}: {result['_detect_error']}")
            errored += 1
        elif result.get("ats_type"):
            print(f"  [ok] {name}: {result['ats_type']} (ats_slug={result['ats_slug']})")
            detected += 1
        else:
            print(f"  [manual] {name}: no ATS fingerprint found -- add css_selector by hand")
            needs_review += 1

        # Drop internal bookkeeping keys before writing to the yaml file.
        result.pop("_detect_error", None)
        result.pop("_needs_manual_review", None)
        final.append(result)

    # Preserve any existing companies not present in this input batch.
    input_names = {e["name"] for e in to_check}
    for name, prior in existing.items():
        if name not in input_names:
            final.append(prior)

    output = {"companies": final}
    header = (
        "# Auto-generated/merged by detect_ats.py -- hand-edit css_selector for\n"
        "# any company marked 'manual' above.\n"
    )
    _COMPANIES_YAML.write_text(header + yaml.safe_dump(output, sort_keys=False, default_flow_style=False))

    print(
        f"\nDone: {detected} auto-detected, {needs_review} need manual css_selector, "
        f"{errored} failed to fetch. Written to {_COMPANIES_YAML}"
    )


if __name__ == "__main__":
    main()
