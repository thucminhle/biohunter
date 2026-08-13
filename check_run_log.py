"""
Prints the most recent run_log entry (any agent -- if you've only run
Scout recently this'll be it) with its `detail` JSON pretty-printed,
since the dashboard has no page for this yet.

Usage (from repo root):
    python check_run_log.py
"""
from __future__ import annotations

import json

from biohunter.db import get_connection, init_schema


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    row = conn.execute(
        """SELECT id, agent, started_at, finished_at, status, detail
           FROM run_log ORDER BY started_at DESC LIMIT 1"""
    ).fetchone()

    if row is None:
        print("No run_log entries yet.")
        return

    run_id, agent, started_at, finished_at, status, detail = row
    print(f"run_log id={run_id}  agent={agent}  status={status}")
    print(f"started_at={started_at}  finished_at={finished_at}")
    print()

    if not detail:
        print("(no detail recorded)")
        return

    try:
        parsed = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        print("detail (raw, not valid JSON):")
        print(detail)
        return

    print(json.dumps(parsed, indent=2))

    errors = parsed.get("errors")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for err in errors:
            print(f"  - {err.get('company')}: {err.get('error')}")


if __name__ == "__main__":
    main()
