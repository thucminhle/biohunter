"""
Persistence for generated drafts (Writer -> Critic -> Revision output),
keyed to a posting. Added alongside the dashboard -- see schema.sql's
`drafts` table comment for why this is a new table rather than columns
bolted onto `postings`.

Nothing in writer.py/critic.py/revision.py/diff.py changes because of
this module. Those stay exactly what they were: pure functions that
take data and return dataclasses, with zero knowledge that a database
exists. This module is the only place that knows how a RevisionResult
gets serialized to/from a DB row -- same "one module owns one concern"
split as the rest of this project.

conn is whatever db.get_connection() returns (libsql_experimental,
SQLite-compatible per schema.sql's own comment) -- every function here
takes it as a parameter rather than opening its own connection, same
convention cli.py's commands already use.
"""
from __future__ import annotations

import dataclasses
import json

from .critic import parse_score
from .revision import RevisionResult, RevisionRound
from .writer import WriterDraft


def _draft_to_dict(d: WriterDraft) -> dict:
    return dataclasses.asdict(d)


def _draft_from_dict(d: dict) -> WriterDraft:
    return WriterDraft(**d)


def _result_to_dict(result: RevisionResult) -> dict:
    return {
        "final_draft": _draft_to_dict(result.final_draft),
        "final_critique": result.final_critique,
        "rounds": [
            {"round_number": r.round_number, "draft": _draft_to_dict(r.draft), "critique": r.critique}
            for r in result.rounds
        ],
    }


def _result_from_dict(d: dict) -> RevisionResult:
    return RevisionResult(
        final_draft=_draft_from_dict(d["final_draft"]),
        final_critique=d["final_critique"],
        rounds=[
            RevisionRound(
                round_number=r["round_number"],
                draft=_draft_from_dict(r["draft"]),
                critique=r["critique"],
            )
            for r in d["rounds"]
        ],
    )


@dataclasses.dataclass
class DraftRecord:
    id: int
    posting_id: int
    generated_at: str
    revision_rounds: int
    final_score: int | None
    result: RevisionResult


def save_draft(conn, posting_id: int, result: RevisionResult) -> int:
    """Persists one generation run and returns its new drafts.id.

    final_score is parsed here (via critic.parse_score) rather than
    left for a reader to recompute every time -- see schema.sql's
    comment on why it's denormalized. If the critique didn't parse
    (see parse_score()'s own docstring), this stores NULL, same
    "unavailable, not zero" contract every other score display in this
    project already follows.
    """
    score_result = parse_score(result.final_critique)
    conn.execute(
        """INSERT INTO drafts (posting_id, revision_rounds, final_score, result_json)
           VALUES (?, ?, ?, ?)""",
        (
            posting_id,
            len(result.rounds) - 1 if result.rounds else 0,
            score_result.score,
            json.dumps(_result_to_dict(result)),
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM drafts WHERE posting_id = ? ORDER BY id DESC LIMIT 1", (posting_id,)
    ).fetchone()
    return row[0]


def _row_to_record(row) -> DraftRecord:
    draft_id, posting_id, generated_at, revision_rounds, final_score, result_json = row
    return DraftRecord(
        id=draft_id,
        posting_id=posting_id,
        generated_at=generated_at,
        revision_rounds=revision_rounds,
        final_score=final_score,
        result=_result_from_dict(json.loads(result_json)),
    )


def get_latest_draft(conn, posting_id: int) -> DraftRecord | None:
    row = conn.execute(
        """SELECT id, posting_id, generated_at, revision_rounds, final_score, result_json
           FROM drafts WHERE posting_id = ? ORDER BY id DESC LIMIT 1""",
        (posting_id,),
    ).fetchone()
    return _row_to_record(row) if row is not None else None


def get_draft_by_id(conn, draft_id: int) -> DraftRecord | None:
    row = conn.execute(
        """SELECT id, posting_id, generated_at, revision_rounds, final_score, result_json
           FROM drafts WHERE id = ?""",
        (draft_id,),
    ).fetchone()
    return _row_to_record(row) if row is not None else None


def latest_draft_index(conn) -> dict[int, DraftRecord]:
    """One query for the dashboard's posting list: the latest draft per
    posting_id, for every posting that has at least one. A posting with
    zero drafts is simply absent from the returned dict -- callers (the
    dashboard's index route) treat that as "not yet generated," not an
    error, same as get_latest_draft() returning None for one posting.
    """
    rows = conn.execute(
        """SELECT d.id, d.posting_id, d.generated_at, d.revision_rounds, d.final_score, d.result_json
           FROM drafts d
           INNER JOIN (
               SELECT posting_id, MAX(id) AS max_id FROM drafts GROUP BY posting_id
           ) latest ON d.posting_id = latest.posting_id AND d.id = latest.max_id"""
    ).fetchall()
    return {row[1]: _row_to_record(row) for row in rows}
