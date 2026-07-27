"""
Usage:
    python -m biohunter.cli run-scout
"""
from __future__ import annotations

import argparse
import datetime
import json

from .db import get_connection, init_schema
from .scout import run_scout


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="biohunter")
    subparsers = parser.add_subparsers(required=True)

    p_scout = subparsers.add_parser("run-scout", help="Run one Scout pass over the company registry")
    p_scout.set_defaults(func=cmd_run_scout)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
