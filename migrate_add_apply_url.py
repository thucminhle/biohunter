"""Migration: add postings.apply_url

Adds a nullable apply_url column to the postings table -- the direct
application link for a specific posting (e.g. LinkedIn shows an "apply
on company site" link distinct from the LinkedIn job URL itself, and
that's the link someone will actually click to apply). Distinct from
companies.careers_url, which is the company's general careers-page
link used by Scout, not a per-posting apply link.

Written against a plain sqlite3 connection (not biohunter.db's
get_connection()) because db.py wasn't uploaded this session, so its
exact import path/signature isn't confirmed -- this is intentionally
self-contained rather than guessing at that interface. If db.py's
get_connection() does something beyond opening the file (e.g. enabling
foreign keys, WAL mode), run this script AFTER confirming that's not
required for a bare ALTER TABLE, or swap the connection line for your
project's real get_connection() import.

Idempotent: checks PRAGMA table_info first, so running it twice is
safe and does nothing the second time.

Usage:
    python migrate_add_apply_url.py path/to/biohunter.db
"""

from __future__ import annotations

import sqlite3
import sys


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(postings)").fetchall()]
        if "apply_url" in cols:
            print("postings.apply_url already exists -- nothing to do.")
            return
        conn.execute("ALTER TABLE postings ADD COLUMN apply_url TEXT")
        conn.commit()
        print("Added postings.apply_url.")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python migrate_add_apply_url.py path/to/biohunter.db")
        sys.exit(1)
    migrate(sys.argv[1])
