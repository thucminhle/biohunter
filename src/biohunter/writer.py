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


def generate_draft(
    llm: LLMClient,
    company_name: str,
    job_title: str,
    job_description: str,
    think: bool = False,
    critique_feedback: str | None = None,
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
    """

    # Branch A: resume summary (variant-select, fallback = first entry)
    summary_catalog = load_catalog(qdrant.fetch_by_section_type("professional_summary", limit=20))
    summary = select_variant(
        llm, SELECTION_ROLE, SUMMARY_INSTRUCTION, job_description, summary_catalog, "summary",
        think=think, critique_feedback=critique_feedback,
    )

    # Branch B pass 1: headings (fallback = full catalog)
    heading_payloads = qdrant.fetch_by_section_type("professional_experience_heading", limit=20)
    selected_headings = select_headings(
        llm, SELECTION_ROLE, job_description, heading_payloads,
        think=think, critique_feedback=critique_feedback,
    )

    # Branch B pass 2: bullets within the selected headings (no fallback)
    bullet_payloads = qdrant.fetch_by_section_type(
        "professional_experience_bullet",
        limit=300,
        extra_filter={"key": "heading", "match": {"any": selected_headings}},
    )
    bullets = select_bullets(
        llm, SELECTION_ROLE, job_description, selected_headings, bullet_payloads,
        think=think, critique_feedback=critique_feedback,
    )

    # Branch C: skills (no fallback)
    skill_payloads = qdrant.fetch_by_section_type("key_skills", limit=50)
    skills = select_skills(
        llm, SELECTION_ROLE, job_description, skill_payloads,
        think=think, critique_feedback=critique_feedback,
    )

    # Always-full sections: no LLM call, just fetch + reshape
    always_payloads = qdrant.fetch_by_section_type(ALWAYS_FULL_SECTION_TYPES, limit=20)
    always = load_always_full_sections(always_payloads)

    # Cover letter branches: 4 independent variant-selects, then a stitch pass
    intro_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_intro", limit=20))
    intro = select_variant(
        llm, SELECTION_ROLE, INTRO_INSTRUCTION, job_description, intro_catalog, "cover letter intro",
        think=think, critique_feedback=critique_feedback,
    )

    story_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_story", limit=20))
    story = select_variant(
        llm, SELECTION_ROLE, STORY_INSTRUCTION, job_description, story_catalog, "cover letter story",
        think=think, critique_feedback=critique_feedback,
    )

    impact_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_impact", limit=20))
    impact = select_variant(
        llm, SELECTION_ROLE, IMPACT_INSTRUCTION, job_description, impact_catalog, "cover letter impact",
        think=think, critique_feedback=critique_feedback,
    )

    gratitude_catalog = load_catalog(qdrant.fetch_by_section_type("cover_letter_gratitude", limit=20))
    gratitude = select_variant(
        llm, SELECTION_ROLE, GRATITUDE_INSTRUCTION, job_description, gratitude_catalog,
        "cover letter gratitude", think=think, critique_feedback=critique_feedback,
    )

    cover_letter = stitch_cover_letter(
        llm, SELECTION_ROLE, job_title, company_name, job_description, intro, story, impact, gratitude,
        think=think, critique_feedback=critique_feedback,
    )

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
    )
