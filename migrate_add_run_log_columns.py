"""
One-off migration: adds job_id/prompt_tokens/completion_tokens/
llm_seconds/duration_seconds to run_log (see schema.sql's comment on
that table for what each column is for -- this exists purely so an
EXISTING database, created before these columns were added, gets them
too, matching schema.sql's CREATE TABLE IF NOT EXISTS for brand-new
databases).

Idempotent: checks each column against PRAGMA table_info(run_log)
before adding it, so re-running this after it already succeeded is a
harmless no-op rather than an error -- same convention as this
project's other migrate_*.py scripts.

Run once, from the project root:
    python migrate_add_run_log_columns.py
"""
from __future__ import annotations

from biohunter.db import get_connection

NEW_COLUMNS = {
    "job_id": "TEXT",
    "prompt_tokens": "INTEGER",
    "completion_tokens": "INTEGER",
    "llm_seconds": "REAL",
    "duration_seconds": "REAL",
}


def main() -> None:
    conn = get_connection()
    existing = {row[1] for row in conn.execute("PRAGMA table_info(run_log)").fetchall()}

    added = []
    for column, sql_type in NEW_COLUMNS.items():
        if column in existing:
            print(f"  already present: run_log.{column}")
            continue
        conn.execute(f"ALTER TABLE run_log ADD COLUMN {column} {sql_type}")
        added.append(column)
        print(f"  added: run_log.{column} {sql_type}")

    conn.commit()
    if added:
        print(f"Done -- added {len(added)} column(s) to run_log.")
    else:
        print("Done -- run_log already had every column, nothing to do.")


if __name__ == "__main__":
    main()
