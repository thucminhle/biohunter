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

from .llm import LLMClient

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
    "submitting as-is."
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
