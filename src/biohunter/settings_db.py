"""
Candidate settings: your name + a contact line, used to fill in the
resume/cover-letter PDF header (resume_pdf.py's candidate_name/
contact_line params, which every existing caller has always left blank
-- see the 2026-08-13 handoff's "candidate name/contact info is never
wired into the PDF export" gap).

Deliberately a dashboard-editable DB row, not a config/*.yaml file --
unlike companies.yaml/search_criteria.yaml (which are meant to be
git-ignored, hand-edited files defining WHAT the search targets),
candidate_settings is closer to drafts.py's territory: something that
changes via a browser form and should take effect without a restart or
a file edit. See schema.sql's candidate_settings table -- one singleton
row (id=1), upserted, never inserted twice.

Same shape as drafts_db.py on purpose: a small dataclass, a get, a
save, no ORM.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CandidateSettings:
    candidate_name: str = ""
    contact_line: str = ""


def get_candidate_settings(conn) -> CandidateSettings:
    """Returns the current settings, or an all-blank CandidateSettings if
    the row has never been saved -- callers (resume_pdf.py's render_*
    functions) already treat blank candidate_name/contact_line as "omit
    the header block", so no special not-yet-configured branch is needed
    here."""
    row = conn.execute(
        "SELECT candidate_name, contact_line FROM candidate_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return CandidateSettings()
    candidate_name, contact_line = row
    return CandidateSettings(candidate_name=candidate_name or "", contact_line=contact_line or "")


def save_candidate_settings(conn, candidate_name: str, contact_line: str) -> None:
    """Upserts the singleton row. SQLite/libSQL's `INSERT ... ON CONFLICT`
    (id=1 is the only possible conflict, per the CHECK constraint) keeps
    this one statement instead of a select-then-insert-or-update dance."""
    conn.execute(
        """INSERT INTO candidate_settings (id, candidate_name, contact_line, updated_at)
           VALUES (1, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             candidate_name = excluded.candidate_name,
             contact_line = excluded.contact_line,
             updated_at = excluded.updated_at""",
        (candidate_name.strip(), contact_line.strip()),
    )
    conn.commit()
