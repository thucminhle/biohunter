"""One-time backfill: promotes existing New/Scored postings that
already have a draft into Kanban's "prepared" column.

dashboard.py's _maybe_promote_to_prepared() (added 2026-09-13) only
fires going forward, right after a NEW draft-generation event -- it
never runs retroactively. Any posting that already had a draft before
that change shipped is stuck showing New/Scored on the Kanban board
despite already having a resume + cover letter ready. This script is
the one-time catch-up for that gap; nothing else in the app writes
status='prepared' outside of _maybe_promote_to_prepared() and this
script performing the exact same transition in bulk.

Same rule as _maybe_promote_to_prepared(): only touches postings
currently 'new' or 'scored'. A posting already 'applied' / 'rejected'
/ 'stale' is left exactly where it is, even if it also has a draft --
this migration doesn't reclassify anything a person already acted on
by hand, same reasoning the live code follows.

Idempotent: the WHERE clause only ever matches new/scored postings
that have a draft, and this script's own UPDATE moves them out of
that set -- so running it a second time finds nothing left to do.

Run once, from the project root:
    python migrate_backfill_prepared_status.py
"""
from __future__ import annotations

from biohunter.db import get_connection


def main() -> None:
    conn = get_connection()

    candidates = conn.execute(
        """SELECT postings.id, companies.name, postings.title
           FROM postings JOIN companies ON postings.company_id = companies.id
           WHERE postings.status IN (\'new\', \'scored\')
             AND postings.id IN (SELECT DISTINCT posting_id FROM drafts)"""
    ).fetchall()

    if not candidates:
        print("Nothing to backfill -- no new/scored posting currently has a draft.")
        return

    print(f"Backfilling {len(candidates)} posting(s) to status=\'prepared\':")
    for posting_id, company, title in candidates:
        print(f"  #{posting_id}  {company} -- {title}")

    conn.executemany(
        "UPDATE postings SET status = \'prepared\' WHERE id = ?",
        [(row[0],) for row in candidates],
    )
    conn.commit()
    print(f"\nDone -- {len(candidates)} posting(s) moved to \'prepared\'.")


if __name__ == "__main__":
    main()
