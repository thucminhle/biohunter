"""
Usage:
    python -m biohunter.cli run-scout
    python -m biohunter.cli list-postings [--exclude KEYWORD,...] [--include KEYWORD,...] [--company NAME]
"""
from __future__ import annotations

import argparse
import datetime
import json

from .config import load_search_criteria
from .db import get_connection, init_schema
from .scout import run_scout

# Fallback defaults if no search_criteria.yaml/example exists at all -- in
# practice load_search_criteria() always finds at least the .example file.
DEFAULT_EXCLUDE_KEYWORDS = ["postdoc", "post-doctoral", "post doctoral", "intern", "internship", "co-op"]

# Same spirit: a blunt, editable default so you're not typing this list every
# time. Includes common per-posting location text on top of city names, since
# ATS location fields vary (some say "South San Francisco, CA", some just
# "Bay Area", some "Remote - US").
DEFAULT_BAY_AREA_LOCATIONS = [
    "bay area", "san francisco", "south san francisco", "oakland", "berkeley",
    "san jose", "redwood city", "foster city", "fremont", "palo alto",
    "menlo park", "emeryville", "mountain view", "santa clara", "hayward",
    "san mateo", "sunnyvale", "vacaville", "richmond, ca", "alameda",
]


def _log_run(conn, status: str, detail: str) -> None:
    conn.execute(
        """INSERT INTO run_log (agent, finished_at, status, detail)
           VALUES ('scout', ?, ?, ?)""",
        (datetime.datetime.now(datetime.timezone.utc).isoformat(), status, detail),
    )
    conn.commit()


def cmd_run_scout(_args: argparse.Namespace) -> None:
    results = run_scout()

    total_new = sum(r.new_postings for r in results)
    errors = [r for r in results if r.strategy == "error"]

    print(f"Scout run: {len(results)} companies checked, {total_new} new postings.\n")
    for r in results:
        if r.strategy == "error":
            print(f"  [ERROR] {r.company_name}: {r.error}")
        else:
            print(f"  {r.company_name} ({r.strategy}): {r.new_postings} new / {r.total_postings} total")

    conn = get_connection()
    init_schema(conn)
    status = "ok" if not errors else "partial"
    detail = json.dumps(
        {
            "companies_checked": len(results),
            "new_postings": total_new,
            "errors": [{"company": r.company_name, "error": r.error} for r in errors],
        }
    )
    _log_run(conn, status, detail)


def cmd_list_postings(args: argparse.Namespace) -> None:
    criteria = load_search_criteria()

    title_exclude = (
        [k.strip().lower() for k in args.exclude.split(",") if k.strip()]
        if args.exclude is not None else criteria.title_exclude
    )
    title_include = (
        [k.strip().lower() for k in args.include.split(",") if k.strip()]
        if args.include is not None else criteria.title_include
    )
    location_include = (
        [k.strip().lower() for k in args.location.split(",") if k.strip()]
        if args.location is not None else criteria.location_include
    )
    location_exclude = criteria.location_exclude

    conn = get_connection()
    init_schema(conn)

    query = """
        SELECT companies.name, postings.title, postings.location, postings.url
        FROM postings JOIN companies ON postings.company_id = companies.id
        WHERE 1=1
    """
    params: list = []
    if not args.include_stale:
        query += " AND postings.status != 'stale'"
    if args.company:
        query += " AND companies.name = ?"
        params.append(args.company)
    query += " ORDER BY companies.name, postings.title"

    rows = conn.execute(query, tuple(params)).fetchall()

    shown = 0
    for company, title, location, url in rows:
        title_lower = title.lower()
        location_lower = (location or "").lower()

        if any(kw in title_lower for kw in title_exclude):
            continue
        if title_include and not any(kw in title_lower for kw in title_include):
            continue
        if any(kw in location_lower for kw in location_exclude):
            continue
        if location_include and not any(kw in location_lower for kw in location_include):
            continue

        print(f"[{company}] {title} -- {location or 'location n/a'}\n    {url}")
        shown += 1

    print(
        f"\n{shown} / {len(rows)} postings shown "
        f"(title_exclude: {', '.join(title_exclude) or 'none'}; "
        f"location_include: {', '.join(location_include) or 'any'})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="biohunter")
    subparsers = parser.add_subparsers(required=True)

    p_scout = subparsers.add_parser("run-scout", help="Run one Scout pass over the company registry")
    p_scout.set_defaults(func=cmd_run_scout)

    p_list = subparsers.add_parser("list-postings", help="List stored postings with keyword/location filtering")
    p_list.add_argument("--exclude", help="Comma-separated title keywords to exclude (default: from search_criteria.yaml)")
    p_list.add_argument("--include", help="Comma-separated title keywords to require, any match (default: from search_criteria.yaml)")
    p_list.add_argument("--location", help="Comma-separated location keywords to require, any match (default: from search_criteria.yaml)")
    p_list.add_argument("--company", help="Filter to a single company name")
    p_list.add_argument("--include-stale", action="store_true", help="Include postings not seen in 30+ days (presumed closed)")
    p_list.set_defaults(func=cmd_list_postings)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
