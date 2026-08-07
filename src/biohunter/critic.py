"""
Critic agent: one blind-review LLM call over a completed WriterDraft,
producing freeform critique text a human (and eventually a revision
loop) can act on.

Deliberately NOT built on selection.py's machinery (parse_json_response,
exact-match validation, catalog fallback) -- there's no catalog to
select from here, just a draft to review, so that machinery would be
unused abstraction. This mirrors stitch_cover_letter()'s shape instead:
one prompt, one LLM call, return the text.

Per ADR-0006 / the 2026-08-06 handoff, this is Phase 2 item #1. It is
intentionally DB-agnostic and persistence-agnostic -- critique_draft()
takes a draft's pieces and returns text, nothing more. Wiring this to
`awaiting_review` status, storage, or a revision loop is item #2's
concern, not this module's.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .llm import LLMClient

logger = logging.getLogger(__name__)

# Fixed section headers the critique is asked to organize under. This
# keeps the output skimmable and gives a revision loop (later) a
# predictable shape to re-feed to Writer as plain text -- no JSON
# parsing needed, Writer's revision prompt can just say "here's the
# critique, revise accordingly" and paste this verbatim.
CRITIC_INSTRUCTION = (
    "You are a skeptical, detail-oriented hiring manager and ATS specialist "
    "reviewing a tailored resume and cover letter against a specific job "
    "description, before the candidate submits it. Be direct and specific -- "
    "vague praise is not useful here. Quote the exact bullet, phrase, or "
    "sentence you are critiquing wherever possible, don't paraphrase it.\n\n"
    "Organize your response under exactly these six headers, in this order, "
    "each as a markdown '## ' heading:\n\n"
    "## ATS & Keyword Coverage\n"
    "Identify important keywords/skills from the job description that are "
    "MISSING from the resume, and note any that are present but buried or "
    "phrased differently than the job posting uses them.\n\n"
    "## Unsupported Claims\n"
    "Flag any bullet, summary line, or cover letter sentence that asserts "
    "something the rest of the resume doesn't substantiate (an unearned "
    "superlative, a skill claimed nowhere else, a metric that seems invented).\n\n"
    "## Weak Bullets\n"
    "Call out specific Professional Experience bullets that are vague, "
    "generic, lack a concrete result, or don't clearly connect to this job "
    "description. Quote them.\n\n"
    "## Weak Summary\n"
    "Assess whether the tailored summary paragraph actually pulls its weight "
    "for THIS posting, or reads generic enough to have been sent anywhere.\n\n"
    "## Cover Letter Critique\n"
    "Assess tone, specificity, and whether the letter reads as genuinely "
    "tailored to this company/role or as a template with placeholders swapped.\n\n"
    "## Overall Recommendation\n"
    "One short paragraph: submit as-is, submit with minor edits, or needs "
    "real revision -- and the single highest-leverage change to make if not "
    "submitting as-is.\n\n"
    "## Score\n"
    "Your honest assessment of how ready this draft is to submit for THIS "
    "posting, as a single integer from 1 (not ready, needs a full rewrite) "
    "to 10 (submit as-is, no changes needed). This must be the ONLY line "
    "in this section -- no preamble, no extra commentary, exactly this "
    "format and nothing else:\n"
    "SCORE: <integer 1-10> -- <one-sentence rationale>"
)

# Matches the strict "SCORE: <int> -- <rationale>" line asked for above.
# Deliberately tolerant of the dash character the model might use (-, --,
# or an em/en dash) and of it possibly wrapping the score in some
# other stray punctuation, since the other six headers in this same
# prompt have already been observed drifting round-to-round (see the
# 2026-08-07 handoff) -- the model complying with five words of format
# instruction perfectly every time isn't something to assume without
# evidence, so the regex is intentionally a little permissive rather
# than a fragile exact match.
_SCORE_LINE_RE = re.compile(
    r"SCORE:\s*(\d{1,2})\s*[-\u2013\u2014:]+\s*(.+)", re.IGNORECASE
)


def critique_draft(
    llm: LLMClient,
    role: str,
    company_name: str,
    job_title: str,
    job_description: str,
    tailored_summary: str,
    tailored_bullets: str,
    cover_letter: str,
    think: bool = False,
) -> str:
    """Runs one blind-review pass over an already-assembled draft.

    Takes the same pieces WriterDraft already carries (tailored_summary,
    tailored_bullets, cover_letter) rather than a WriterDraft object
    directly, so this module has zero import-time dependency on
    writer.py -- callers (CLI, future revision loop) do the unpacking.

    think: same per-call flag as every Writer branch (see
    selection.py's select_variant() docstring) -- pass explicitly,
    never omit, since omitting it does not behave like think=False.
    """
    prompt = (
        f"{CRITIC_INSTRUCTION}\n\n"
        f"Company: {company_name}\n"
        f"Job Title: {job_title or '(not given)'}\n\n"
        f"Job Description:\n{job_description}\n\n"
        f"{'=' * 70}\n"
        f"TAILORED SUMMARY:\n{tailored_summary}\n\n"
        f"TAILORED RESUME BODY:\n{tailored_bullets}\n\n"
        f"COVER LETTER:\n{cover_letter}\n"
    )

    response = llm.complete(role, [{"role": "user", "content": prompt}], think=think)
    return response.text.strip()


@dataclass
class ScoreResult:
    score: int | None  # 1-10, or None if the model's output didn't parse
    rationale: str | None  # one sentence, or None alongside a None score


def parse_score(critique_text: str) -> ScoreResult:
    """Extracts the '## Score' section's SCORE: line from critique_draft()'s
    output. Deliberately a separate function rather than folded into
    critique_draft() itself or a change to that function's return type --
    critique_draft() keeps returning the same freeform str it always has
    (zero change for revision.py/cli.py's existing handling of it), and a
    caller that wants the score calls this on the text it already has.

    This is display-only by design (see the 2026-08-07 ATS Score
    discussion) -- nothing in this project reads ScoreResult to decide
    whether to keep revising. Never raises: a model that doesn't comply
    with the SCORE: format degrades to ScoreResult(None, None) with a
    warning logged, matching every other parse-with-fallback in this
    project (see selection.py's parse_json_response) rather than
    crashing a CLI command over a formatting miss in one section of an
    otherwise-usable critique.
    """
    match = _SCORE_LINE_RE.search(critique_text or "")
    if not match:
        logger.warning(
            "critique text has no parseable 'SCORE: <n> -- <rationale>' line "
            "-- score will display as unavailable, but the rest of the "
            "critique is unaffected."
        )
        return ScoreResult(score=None, rationale=None)

    raw_score, rationale = match.group(1), match.group(2).strip()
    score = int(raw_score)
    if not (1 <= score <= 10):
        logger.warning(
            "critique's SCORE line parsed to %d, outside the requested 1-10 "
            "range -- keeping it as-is rather than silently clamping, since "
            "clamping would hide a prompt-compliance issue worth noticing.",
            score,
        )
    return ScoreResult(score=score, rationale=rationale)
