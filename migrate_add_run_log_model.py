"""
One-off migration: adds run_log.model (TEXT, nullable).

Needed because CREATE TABLE IF NOT EXISTS (schema.sql / db.py's
init_schema()) never alters an already-existing table. This is
SEPARATE from whatever migration already added run_log's job_id /
prompt_tokens / completion_tokens / llm_seconds / duration_seconds
columns (the per-run token-usage rework) -- if that migration hasn't
been run yet either, run it first; this script only adds `model` and
assumes the other five columns already exist.

Added 2026-08-23. Run this ONCE against your real data/biohunter.db (or
Turso db) after pulling the updated schema.sql, before starting the
dashboard again.

Safe to run multiple times: checks whether the column already exists
via PRAGMA table_info before attempting to add it, so re-running after
it's already applied is a no-op, not an error.
"""
from __future__ import annotations

from biohunter.db import get_connection


def migrate() -> None:
    conn = get_connection()
    columns = [row[1] for row in conn.execute("PRAGMA table_info(run_log)").fetchall()]

    if "model" in columns:
        print("run_log.model already exists -- nothing to do.")
        return

    # Not fatal if missing, but worth flagging loudly -- model tracking
    # is meant to sit alongside the per-run columns, and a table that
    # doesn't have them yet is a sign the other migration hasn't run.
    expected_prereqs = {"job_id", "prompt_tokens", "completion_tokens", "llm_seconds", "duration_seconds"}
    missing_prereqs = expected_prereqs - set(columns)
    if missing_prereqs:
        print(
            f"WARNING: run_log is missing {sorted(missing_prereqs)} -- the "
            "per-run token-usage migration doesn't appear to have run yet. "
            "Adding run_log.model anyway, but /tokens may not work fully "
            "until that migration is also applied."
        )

    conn.execute("ALTER TABLE run_log ADD COLUMN model TEXT")
    conn.commit()
    print("Added run_log.model (TEXT, nullable).")


if __name__ == "__main__":
    migrate()
