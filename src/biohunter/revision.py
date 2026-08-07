"""
Revision loop: Writer -> Critic -> Writer Revision -> Critic -> ... for a
configurable number of rounds, then hands off to Human Review (ADR-0006
Phase 2 item #2, per the 2026-08-06 handoff).

This module is intentionally thin -- it owns only the looping and the
history record. All the real work (verbatim-catalog selection, the
no-invented-facts guarantee, the critique prompt) already lives in
writer.py/selection.py/critic.py; run_revision_loop() just calls them
repeatedly, feeding each round's critique into the next round's
generate_draft() call via the critique_feedback param those modules
already accept.

Like critic.py, this stays DB/persistence-agnostic on purpose -- no
`awaiting_review` status writes, no storage. A caller (CLI today, a
future Captain auto-trigger path later) decides what to persist and
when; this module just produces the final draft + critique + full
round-by-round history so the caller has everything it needs to persist
however it wants.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .critic import critique_draft
from .llm import LLMClient
from .writer import WriterDraft, generate_draft

CRITIC_ROLE = "critic_review"


@dataclass
class RevisionRound:
    round_number: int  # 0 = first draft (no feedback applied yet), 1+ = a revision
    draft: WriterDraft
    critique: str


@dataclass
class RevisionResult:
    final_draft: WriterDraft
    final_critique: str
    rounds: list[RevisionRound] = field(default_factory=list)


def run_revision_loop(
    llm: LLMClient,
    company_name: str,
    job_title: str,
    job_description: str,
    revision_rounds: int = 1,
    think: bool = False,
) -> RevisionResult:
    """Generates a first draft, critiques it, then re-generates and
    re-critiques up to `revision_rounds` more times, feeding each
    round's critique into the next round's generation as
    critique_feedback.

    revision_rounds counts REVISIONS after the first draft -- e.g.
    revision_rounds=2 means: draft -> critique -> revise -> critique ->
    revise -> critique, i.e. 3 drafts and 3 critiques total, matching
    the handoff's "revision_rounds: 2" example. revision_rounds=0 just
    runs Writer once and Critic once, with no revision (useful for
    comparing against critic.py's standalone behavior).

    Every round reuses the same `think` value across all of Writer's
    branches and Critic's call, same as generate_draft() and
    critique_draft() already do individually -- no partial-thinking
    runs within a single round.

    Does not decide when to stop early (e.g. on a strong "submit as-is"
    recommendation) -- it always runs the full requested round count.
    Early-stopping on Critic's recommendation is a reasonable future
    refinement, not built here to keep this pass's scope to what the
    handoff actually asked for.
    """
    draft = generate_draft(llm, company_name, job_title, job_description, think=think)
    critique = critique_draft(
        llm, CRITIC_ROLE,
        company_name=company_name, job_title=job_title, job_description=job_description,
        tailored_summary=draft.tailored_summary, tailored_bullets=draft.tailored_bullets,
        cover_letter=draft.cover_letter, think=think,
    )
    rounds = [RevisionRound(round_number=0, draft=draft, critique=critique)]

    for round_number in range(1, revision_rounds + 1):
        draft = generate_draft(
            llm, company_name, job_title, job_description, think=think, critique_feedback=critique
        )
        critique = critique_draft(
            llm, CRITIC_ROLE,
            company_name=company_name, job_title=job_title, job_description=job_description,
            tailored_summary=draft.tailored_summary, tailored_bullets=draft.tailored_bullets,
            cover_letter=draft.cover_letter, think=think,
        )
        rounds.append(RevisionRound(round_number=round_number, draft=draft, critique=critique))

    return RevisionResult(final_draft=draft, final_critique=critique, rounds=rounds)
