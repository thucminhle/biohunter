"""
Orchestrates one full Writer pass for a single job posting: runs every
n8n-equivalent selection branch against Qdrant + LLMClient, stitches the
cover letter, and assembles the final draft resume + cover letter text.

This is the native replacement for the n8n workflow's node graph from
"split jobs" through "assemble draft resume" (see ADR-0006 build order,
step 1). ATS scoring, critique, and the human-approval gate are steps
2/3 — not built here yet; generate_draft() stops exactly where n8n's
"assemble draft resume" node did.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import qdrant
from .llm import LLMClient
from .selection import (
    ALWAYS_FULL_SECTION_TYPES,
    GRATITUDE_INSTRUCTION,
    IMPACT_INSTRUCTION,
    INTRO_INSTRUCTION,
    STORY_INSTRUCTION,
    SUMMARY_INSTRUCTION,
    assemble_draft,
    load_always_full_sections,
    load_catalog,
    select_bullets,
    select_headings,
    select_skills,
    select_variant,
    stitch_cover_letter,
)

# Every branch — including the cover-letter stitch pass — uses this one
# role, matching the n8n reference implementation's single-model design
# (gemma4:12b-mlx for everything). Deliberately NOT writer_coverletter
# (Anthropic): ADR-0006 says port first, verify parity, refine model
# routing later. Routing the stitch pass to a different model here would
# make any n8n-vs-native parity check meaningless — you'd be comparing
# two different models' output, not checking whether the port is right.
SELECTION_ROLE = "writer_selection"


@dataclass
class WriterDraft:
    company_name: str
    job_title: str
    tailored_summary: str
    tailored_bullets: str
    cover_letter: str
    # Raw verbatim selections behind cover_letter's stitched text --
    # added alongside the deviation-control feature (2026-08-13 handoff)
    # so a revision round can tell whether the 4 underlying picks
    # actually changed, and skip re-running stitch_cover_letter()'s free-
    # form rewrite entirely when they didn't (see generate_draft()'s
    # prev_cover_letter_blocks/prev_cover_letter params below). Not used
    # anywhere else in the draft -- cover_letter remains the one field
    # every existing caller (resume_pdf.py, report.py) actually renders.
    cover_letter_blocks: tuple[str, str, str, str] = ("", "", "", "")


def generate_draft(
    llm: LLMClient,
    company_name: str,
    job_title: str,
    job_description: str,
    think: bool = False,
    critique_feedback: str | None = None,
    stability: str = "balanced",
    prev_cover_letter_blocks: tuple[str, str, str, str] | None = None,
    prev_cover_letter: str | None = None,
    on_step: Callable[[str], None] | None = None,
) -> WriterDraft:
    """Runs the full 8-branch selection pipeline for one posting and
    returns the assembled draft. Mirrors n8n's node graph branch-for-
    branch; see selection.py for the fallback-behavior differences
    between branches (variant vs. heading vs. bullet/skills).

    think mirrors n8n's per-request `think` flag, sourced from the
    original form's "Thorough (with thinking)" / "Fast (no thinking)"
    toggle -- every branch below gets the SAME value, matching n8n's
    single `split jobs`-derived flag applied uniformly across all 9
    LLM calls. Default False: an isolated timing test (see
    docs/handoffs/2026-08-05-n8n-python-parity-debugging.md) found
    think=False on the native Ollama endpoint ~4-6x faster than
    omitting the flag (which behaves like True, not False), and roughly
    matches n8n's own observed ~5-minute end-to-end runtime. Pass
    think=True to run the "Thorough" mode instead.

    critique_feedback: optional prior-round Critic output (see
    revision.py's run_revision_loop()). None (the default) reproduces
    the original first-draft behavior exactly -- every branch call
    below only receives it when a caller explicitly passes it, so this
    param is a no-op for every existing (non-revision) caller. When
    given, it's forwarded to every branch that can act on it (all 8
    selection calls); assemble_draft() itself has no LLM call to feed
    it to.

    stability: "strict" | "balanced" (default) | "loose" -- forwarded to
    every select_* branch and to stitch_cover_letter() (see selection.py's
    module-level _STABILITY_SUFFIXES comment). Controls how strongly a
    revision round is told to keep vs. reconsider its previous picks;
    "balanced" reproduces the original prompts exactly, so this param is
    a no-op for every existing (pre-deviation-control) caller.

    prev_cover_letter_blocks / prev_cover_letter: the PRIOR round's
    WriterDraft.cover_letter_blocks and .cover_letter (see revision.py's
    run_revision_loop(), the only real caller of these two params).
    When both are given AND this round's freshly-selected (intro.text,
    story.text, impact.text, gratitude.text) tuple exactly matches
    prev_cover_letter_blocks, stitch_cover_letter() is skipped entirely
    and prev_cover_letter is reused verbatim -- there is nothing for a
    free-form rewrite pass to usefully do when none of its four inputs
    changed, and skipping it removes a real source of round-to-round
    drift the 2026-08-13 handoff flagged (stitch_cover_letter() is the
    one branch that isn't exact-match validated against a catalog, so a
    needless re-run was the most likely place unwanted rewording crept
    in). Both None (the default) reproduces the original always-stitch
    behavior exactly -- a no-op for every non-revision caller and for
    round 0 of every revision (there IS no prior round to compare against).

    on_step: optional callback invoked once after each of the 9 units of
    work below completes (the 8 LLM branches, plus the stitch-or-skip
    decision) with a short human-readable label, e.g. "bullets" or
    "cover letter: stitch (skipped, unchanged)". Purely a progress-
    reporting hook -- dashboard.py uses it to drive a real step-count
    progress bar (see run_revision_loop()'s own on_step docstring for
    how the total step count is computed across rounds); it does not
    affect what gets generated. None (the default) is a no-op for every
    existing caller, same contract as every other optional param here.
    """
    def _step(label: str) -> None:
        if on_step is not None:
            on_step(label)

    # Branch A: resume summary (variant-select, fallback = first entry)
    summary_catalog = load_catalog(qdrant.fetch_by_section_type("professional_summary", limit=20))
    summary = select_variant(
        llm, SELECTION_ROLE, SUMMARY_INSTRUCTION, job_description, summary_catalog, "summary",
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("summary")

    # Branch B pass 1: headings (fallback = full catalog)
    heading_payloads = qdrant.fetch_by_section_type("professional_experience_heading", limit=20)
    selected_headings = select_headings(
        llm, SELECTION_ROLE, job_description, heading_payloads,
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("headings")

    # Branch B pass 2: bullets within the selected headings (no fallback)
    bullet_payloads = qdrant.fetch_by_section_type(
        "professional_experience_bullet",
        limit=300,
        extra_filter={"key": "heading", "match": {"any": selected_headings}},
    )
    bullets = select_bullets(
        llm, SELECTION_ROLE, job_description, selected_headings, bullet_payloads,
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("bullets")

    # Branch C: skills (no fallback)
    skill_payloads = qdrant.fetch_by_section_type("key_skills", limit=50)
    skills = select_skills(
        llm, SELECTION_ROLE, job_description, skill_payloads,
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("skills")

    # Always-full sections: no LLM call, just fetch + reshape
    always_payloads = qdrant.fetch_by_section_type(ALWAYS_FULL_SECTION_TYPES, limit=20)
    always = load_always_full_sections(always_payloads)

    # Cover letter branches: 4 independent variant-selects, then a stitch pass
    intro_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_intro", limit=20))
    intro = select_variant(
        llm, SELECTION_ROLE, INTRO_INSTRUCTION, job_description, intro_catalog, "cover letter intro",
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("cover letter: intro")

    story_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_story", limit=20))
    story = select_variant(
        llm, SELECTION_ROLE, STORY_INSTRUCTION, job_description, story_catalog, "cover letter story",
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("cover letter: story")

    impact_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_impact", limit=20))
    impact = select_variant(
        llm, SELECTION_ROLE, IMPACT_INSTRUCTION, job_description, impact_catalog, "cover letter impact",
        think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("cover letter: impact")

    gratitude_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_gratitude", limit=20))
    gratitude = select_variant(
        llm, SELECTION_ROLE, GRATITUDE_INSTRUCTION, job_description, gratitude_catalog,
        "cover letter gratitude", think=think, critique_feedback=critique_feedback, stability=stability,
    )
    _step("cover letter: gratitude")

    # Skip the free-form stitch pass entirely when nothing it would act on
    # actually changed from the prior round -- see generate_draft()'s own
    # docstring for why. This is the one branch that isn't exact-match
    # validated against a catalog, so re-running it needlessly was the
    # most likely source of round-to-round wording drift in the cover
    # letter (2026-08-13 handoff).
    current_blocks = (intro.text, story.text, impact.text, gratitude.text)
    if prev_cover_letter_blocks is not None and prev_cover_letter is not None \
            and current_blocks == prev_cover_letter_blocks:
        cover_letter = prev_cover_letter
        _step("cover letter: stitch (skipped, unchanged)")
    else:
        cover_letter = stitch_cover_letter(
            llm, SELECTION_ROLE, job_title, company_name, job_description, intro, story, impact, gratitude,
            think=think, critique_feedback=critique_feedback, stability=stability,
        )
        _step("cover letter: stitch")

    draft = assemble_draft(
        summary_text=summary.text,
        bullets_markdown=bullets.tailored_bullets,
        skills_markdown=skills.tailored_skills,
        always=always,
        cover_letter=cover_letter,
    )

    return WriterDraft(
        company_name=company_name,
        job_title=job_title,
        tailored_summary=draft.tailored_summary,
        tailored_bullets=draft.tailored_bullets,
        cover_letter=draft.cover_letter,
        cover_letter_blocks=current_blocks,
    )
