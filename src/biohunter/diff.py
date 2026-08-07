"""
Resume Diff: renders what changed (or didn't) between consecutive rounds
of a revision loop (ADR-0006 Phase 2 item #1, per the 2026-08-07 handoff).

RevisionResult.rounds already carries every round's full WriterDraft --
this module adds no new data, it's a rendering pass over what
revision.py already produces. Like critic.py/revision.py, it stays
persistence-agnostic: pure functions in, dataclasses out, no printing,
no storage. cli.py decides how to display the result.

Diffs are computed per-section (summary / bullets / cover letter)
rather than as one blob over the whole draft, matching how every other
part of this project (writer.py's branches, verify-revision's printout)
already treats these three pieces as independent.

Unchanged sections are reported explicitly (changed=False, empty diff
text) rather than omitted. This project already got burned once this
session by a branch silently no-op'ing and looking indistinguishable
from "revision happened" -- a diff step that quietly skips unchanged
sections would hide exactly that failure mode instead of surfacing it.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .revision import RevisionResult
from .writer import WriterDraft

# The three WriterDraft fields diffed independently. Kept as a plain
# tuple of (attribute_name, display_label) rather than hardcoding three
# separate diff calls -- adding a fourth diffable field later (if
# WriterDraft ever grows one) means adding one entry here, not one more
# copy-pasted call at every call site.
_DIFF_SECTIONS: tuple[tuple[str, str], ...] = (
    ("tailored_summary", "Tailored Summary"),
    ("tailored_bullets", "Tailored Bullets"),
    ("cover_letter", "Cover Letter"),
)


@dataclass
class SectionDiff:
    section: str  # display label, e.g. "Tailored Summary"
    changed: bool
    diff_text: str  # unified diff; "" when changed is False


@dataclass
class RoundDiff:
    round_from: int
    round_to: int
    sections: list[SectionDiff]


def diff_drafts(
    prev: WriterDraft, curr: WriterDraft, from_label: str = "before", to_label: str = "after"
) -> list[SectionDiff]:
    """Diffs two drafts section-by-section (order: summary, bullets,
    cover letter -- matching how verify-writer/verify-revision already
    print sections). from_label/to_label are cosmetic only, used as the
    unified-diff header's ---/+++ filenames; diff_revision_result()
    passes round numbers, direct callers can leave the defaults or pass
    their own.

    Standalone and usable outside a RevisionResult -- e.g. comparing
    two arbitrary WriterDraft objects, not just adjacent revision
    rounds -- since it takes drafts directly rather than a RevisionRound.
    """
    results = []
    for attr, label in _DIFF_SECTIONS:
        prev_text = getattr(prev, attr) or ""
        curr_text = getattr(curr, attr) or ""

        if prev_text == curr_text:
            results.append(SectionDiff(section=label, changed=False, diff_text=""))
            continue

        diff_lines = difflib.unified_diff(
            prev_text.splitlines(),
            curr_text.splitlines(),
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
        results.append(
            SectionDiff(section=label, changed=True, diff_text="\n".join(diff_lines))
        )
    return results


def diff_revision_result(result: RevisionResult) -> list[RoundDiff]:
    """Diffs every consecutive pair of rounds in a RevisionResult.

    revision_rounds=2 (3 drafts total, per run_revision_loop()'s
    docstring) produces 2 RoundDiffs: round 0->1 and round 1->2. A
    single-round run (revision_rounds=0, just Writer+Critic once) has
    only one entry in result.rounds and produces an empty list here --
    there's nothing to diff against, and callers (see cli.py) should
    treat an empty list as "no revisions ran," not an error.
    """
    return [
        RoundDiff(
            round_from=prev_round.round_number,
            round_to=curr_round.round_number,
            sections=diff_drafts(
                prev_round.draft, curr_round.draft,
                from_label=f"round {prev_round.round_number}",
                to_label=f"round {curr_round.round_number}",
            ),
        )
        for prev_round, curr_round in zip(result.rounds, result.rounds[1:])
    ]
