"""
Diagnostic: mirrors db.py's exact statement-splitting + execute logic
against your ACTUAL schema.sql file (found the same way db.py finds
it -- repo root, next to this script), and reports which statement (if
any) fails, with its text.

Usage (drop this in your repo ROOT, next to schema.sql, then run):
    python check_schema.py
"""
from __future__ import annotations

import pathlib

import libsql_experimental as libsql

_SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "schema.sql"


def _split_statements(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]


def main() -> None:
    print(f"Reading schema from: {_SCHEMA_PATH}")
    if not _SCHEMA_PATH.exists():
        print("!! That file does not exist at this path.")
        return
    sql = _SCHEMA_PATH.read_text()

    conn = libsql.connect(":memory:")
    statements = _split_statements(sql)
    print(f"Split into {len(statements)} statement(s).\n")

    for i, stmt in enumerate(statements):
        try:
            conn.execute(stmt)
            print(f"[{i}] OK")
        except Exception as e:
            print(f"[{i}] FAILED: {e!r}")
            print("----- statement text -----")
            print(stmt)
            print("---------------------------")
            return

    print("\nAll statements parsed and applied cleanly against an in-memory DB.")


if __name__ == "__main__":
    main()
