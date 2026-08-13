"""
One-time migration: adds the repost-tracking columns to an EXISTING
postings table (schema.sql's CREATE TABLE IF NOT EXISTS won't touch a
table that already exists, so a fresh install gets these columns for
free but your current local DB needs this run once).

Safe to run more than once -- each ALTER TABLE is wrapped so an
"already exists" error is swallowed and reported, not raised.

Usage:
    python migrate_repost_tracking.py

Run this from the project root (same place you'd run `python -m
biohunter.db`), so the default data/biohunter.db path resolves the
same way.
"""
from __future__ import annotations

from biohunter.db import get_connection

_NEW_COLUMNS = [
    ("stale_at", "TEXT"),
    ("reposted_from_id", "INTEGER REFERENCES postings(id)"),
    ("repost_match_type", "TEXT"),
    ("repost_similarity", "REAL"),
    ("repost_turnaround_days", "REAL"),
]


def main() -> None:
    conn = get_connection()
    added, skipped = [], []

    for col_name, col_type in _NEW_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE postings ADD COLUMN {col_name} {col_type}")
            added.append(col_name)
        except Exception as e:
            # libsql/sqlite both raise on duplicate column, message varies
            # slightly by backend -- don't pattern-match the string, just
            # treat any failure here as "already there" and move on.
            skipped.append((col_name, str(e)))

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_postings_reposted_from ON postings(reposted_from_id)"
    )
    conn.commit()

    if added:
        print(f"Added columns: {', '.join(added)}")
    if skipped:
        print("Skipped (already present or error):")
        for col_name, err in skipped:
            print(f"  {col_name}: {err}")
    if not added and not skipped:
        print("No columns to add.")
    print("idx_postings_reposted_from ensured.")


if __name__ == "__main__":
    main()
