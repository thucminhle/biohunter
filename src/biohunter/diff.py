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
import re
from dataclasses import dataclass, field

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

# Which sections get word-level diffing vs. line-level. tailored_bullets
# already has one bullet per line ("- some bullet"), so difflib's normal
# line-based unified_diff already reads fine there. tailored_summary and
# cover_letter are prose paragraphs with few or no internal line breaks
# -- diffing THOSE by line produces one "line" that IS the entire
# paragraph, so any change at all renders as "the whole paragraph was
# deleted, the whole new paragraph was added" with no visible word-level
# distinction (the 2026-08-13 handoff's "long horizontal strings of
# code" complaint). Word-level diffing actually shows what changed.
_WORD_DIFF_SECTIONS = {"tailored_summary", "cover_letter"}

# Splits on whitespace while keeping the whitespace as its own token, so
# re-joining diffed tokens reproduces the original spacing exactly
# rather than collapsing every gap to a single space.
_WORD_SPLIT_RE = re.compile(r"\s+|\S+")


@dataclass
class SectionDiff:
    section: str  # display label, e.g. "Tailored Summary"
    changed: bool
    mode: str = "line"  # "line" (diff_text is a unified diff) or "word" (word_ops instead)
    diff_text: str = ""  # unified diff text; populated when mode == "line" and changed
    # (tag, token) pairs, tag in {"equal", "delete", "insert"}; populated
    # when mode == "word" and changed. Tokens already include their own
    # surrounding whitespace (see _WORD_SPLIT_RE) so "".join(text for
    # _, text in word_ops) reproduces either side's original spacing.
    word_ops: list[tuple[str, str]] = field(default_factory=list)


def _word_diff_ops(prev_text: str, curr_text: str) -> list[tuple[str, str]]:
    """Word-level SequenceMatcher diff for prose sections -- see the
    module-level _WORD_DIFF_SECTIONS comment for why line-diffing a
    paragraph doesn't produce anything readable. autojunk=False:
    SequenceMatcher's default autojunk heuristic can misbehave on text
    with a repeated common word (e.g. "the")  appearing very often,
    which prose routinely does -- not worth the risk for text this
    short (a summary paragraph or cover letter, never megabytes)."""
    prev_tokens = _WORD_SPLIT_RE.findall(prev_text)
    curr_tokens = _WORD_SPLIT_RE.findall(curr_text)
    matcher = difflib.SequenceMatcher(a=prev_tokens, b=curr_tokens, autojunk=False)

    ops: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append(("equal", "".join(prev_tokens[i1:i2])))
        elif tag == "delete":
            ops.append(("delete", "".join(prev_tokens[i1:i2])))
        elif tag == "insert":
            ops.append(("insert", "".join(curr_tokens[j1:j2])))
        elif tag == "replace":
            ops.append(("delete", "".join(prev_tokens[i1:i2])))
            ops.append(("insert", "".join(curr_tokens[j1:j2])))
    return ops


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
        mode = "word" if attr in _WORD_DIFF_SECTIONS else "line"

        if prev_text == curr_text:
            results.append(SectionDiff(section=label, changed=False, mode=mode))
            continue

        if mode == "word":
            results.append(
                SectionDiff(
                    section=label, changed=True, mode="word",
                    word_ops=_word_diff_ops(prev_text, curr_text),
                )
            )
            continue

        diff_lines = difflib.unified_diff(
            prev_text.splitlines(),
            curr_text.splitlines(),
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
        results.append(
            SectionDiff(section=label, changed=True, mode="line", diff_text="\n".join(diff_lines))
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
