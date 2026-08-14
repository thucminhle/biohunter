from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .llm import LLMClient

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|```\s*$", re.MULTILINE)


def strip_fences(text: str) -> str:
    """Ports stripFences() from every n8n "parse X selection" node —
    models sometimes wrap JSON in ```json ... ``` even when told not to."""
    return _FENCE_RE.sub("", text or "").strip()


def parse_json_response(text: str, default: dict) -> dict:
    """Ports the try/catch-with-default pattern every n8n parse node
    used. Never raises — a malformed response degrades to `default`
    rather than crashing the whole branch, matching the reference
    implementation's behavior exactly (it never crashed on bad JSON
    either, it fell back)."""
    try:
        match = re.search(r"\{[\s\S]*\}", strip_fences(text))
        if not match:
            return default
        return json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Deviation/stability control (2026-08-13 handoff: "revisions are small
# tweaks, not major changes" vs. "vary the deviation... to better match
# the job description"). Exposed as a per-generate-request setting from
# the dashboard, not a global config value -- see revision.py/writer.py.
#
# Deliberately NOT a rewrite of the base critique_feedback sentence each
# branch already has (see select_variant()/select_headings()/
# select_bullets()/select_skills() below) -- "balanced" (the default)
# reproduces the exact prior wording and behavior with zero change, so
# every existing (pre-stability-param) call site stays a no-op. "strict"
# and "loose" only ADD a clause on top of that, never remove the base one.
# ---------------------------------------------------------------------------

_STABILITY_SUFFIXES: dict[str, str] = {
    "strict": (
        " Strongly prefer keeping your previous selection here -- only swap it out "
        "if the feedback specifically flags THIS item as weak, missing, or a poor "
        "fit. Do not change something just because a different catalog entry might "
        "also work; staying close to what was already selected matters more than "
        "optimizing further unless the feedback says otherwise."
    ),
    "balanced": "",
    "loose": (
        " Don't hesitate to select something different from before if it's a "
        "better match for THIS specific job description -- the goal is the best "
        "possible fit for this posting, not consistency with earlier rounds."
    ),
}


def _stability_suffix(stability: str) -> str:
    """Unknown values degrade to 'balanced' (no-op) rather than raising --
    same 'degrade, don't crash' pattern as parse_json_response()."""
    return _STABILITY_SUFFIXES.get(stability, "")


@dataclass
class CatalogEntry:
    label: str
    text: str
    alignment_text: str = ""


def load_catalog(payloads: list[dict]) -> list[CatalogEntry]:
    """Turns raw Qdrant payloads into CatalogEntry objects. Every
    variant-select branch's payload has at least label/text;
    alignment_text only exists on the intro catalog, defaults to ''
    for the other four (matching n8n's `alignment_text: p.payload.alignment_text || ''`)."""
    return [
        CatalogEntry(
            label=p.get("label", ""),
            text=p.get("text", ""),
            alignment_text=p.get("alignment_text", "") or "",
        )
        for p in payloads
    ]


def _catalog_text(catalog: list[CatalogEntry]) -> str:
    parts = []
    for c in catalog:
        entry = f"Label: {c.label}\nText: {c.text}"
        if c.alignment_text:
            entry += f"\nSupporting alignment: {c.alignment_text}"
        parts.append(entry)
    return "\n\n---\n\n".join(parts)


@dataclass
class VariantSelection:
    label: str
    text: str
    alignment_text: str = ""


def select_variant(
    llm: LLMClient,
    role: str,
    instruction: str,
    job_description: str,
    catalog: list[CatalogEntry],
    branch_name: str,
    think: bool = False,
    critique_feedback: str | None = None,
    stability: str = "balanced",
) -> VariantSelection:
    """The shape shared by summary/intro/story/impact/gratitude: show the
    model a catalog of {label, text} entries, ask it to pick exactly one
    label verbatim, exact-match the answer back against the catalog,
    fall back to the first catalog entry (with a logged warning) if the
    model's answer doesn't exact-match anything. Ports n8n's five nearly
    identical "select X" + "parse X selection" node pairs into one
    function, parameterized by the one thing that actually differs:
    the instruction sentence.

    branch_name is just for the warning log message, so a bad selection
    is traceable to which of the 5 branches produced it — mirrors the
    "[Branch A]" / "[Cover Letter - Story]" prefixes n8n's console.warn
    calls used.

    think mirrors n8n's per-request `think` flag (sourced from the form's
    "Thorough (with thinking)" / "Fast (no thinking)" toggle) -- NEVER
    omit this when calling llm.complete(). An isolated timing test (see
    docs/handoffs/2026-08-05-n8n-python-parity-debugging.md) found that
    omitting `think` entirely does NOT behave like think=False -- it runs
    closer to think=True, ~4-6x slower on the same prompt. Default here
    is False to match n8n's apparent actual runtime (~5 min end-to-end),
    not because "false" is obviously correct in the abstract.

    critique_feedback: optional prior-round Critic output (see
    revision.py). When given, it's appended as context so the model can
    pick a DIFFERENT catalog label this round if the feedback warrants
    -- the selection is still constrained to the catalog (never free
    rewriting), matching every other branch's verbatim-only guarantee.
    None (the default) reproduces the original prompt exactly, so this
    param is a no-op for every existing (non-revision) caller.

    stability: "strict" | "balanced" (default) | "loose" -- see the
    module-level _STABILITY_SUFFIXES comment. "balanced" reproduces the
    original prompt text exactly (no-op for every existing caller);
    "strict"/"loose" append one extra clause to the critique_feedback
    text, only when critique_feedback is actually given (nothing to
    bias on the first, feedback-free round).
    """
    prompt = (
        f"{instruction} "
        'Respond with ONLY valid JSON, no markdown code fences, no other text, '
        'in this exact shape: {"selected_label": "<label>"}.'
        f"\n\nJob description:\n{job_description}"
        f"\n\nCatalog:\n{_catalog_text(catalog)}"
    )
    if critique_feedback:
        prompt += (
            f"\n\nA prior draft using this catalog was reviewed and received this "
            f"feedback -- consider it, and select a different label than before if "
            f"the feedback suggests a better fit exists in the catalog:\n{critique_feedback}"
            f"{_stability_suffix(stability)}"
        )

    response = llm.complete(role, [{"role": "user", "content": prompt}], think=think, json_mode=True)
    logger.debug("[%s] raw response: %r", branch_name, response.text)
    parsed = parse_json_response(response.text, default={"selected_label": None})

    selected_label = parsed.get("selected_label")
    match = next((c for c in catalog if c.label == selected_label), None)

    if match is None:
        labels = [c.label for c in catalog]
        logger.warning(
            "[%s] selected_label %r did not exact-match any catalog label (%s). "
            "Falling back to first catalog entry.",
            branch_name, selected_label, labels,
        )
        match = catalog[0]

    return VariantSelection(label=match.label, text=match.text, alignment_text=match.alignment_text)


# Instruction sentences ported verbatim from the n8n export's "format X
# catalog" nodes — the only thing that varies between the 5 branches this
# module covers. Keep these exact; changing wording here is a prompt
# change, out of scope for the port itself (ADR-0006).
SUMMARY_INSTRUCTION = (
    "You are selecting exactly ONE pre-written resume summary paragraph that best "
    "matches this job description. Choose one label from the catalog below verbatim "
    "-- do not edit, rephrase, merge, or invent."
)
INTRO_INSTRUCTION = (
    "You are selecting exactly ONE pre-written cover letter introduction paragraph "
    "that best matches this job description. Choose one label from the catalog below "
    "verbatim -- do not edit, rephrase, merge, or invent."
)
STORY_INSTRUCTION = (
    "You are selecting exactly ONE pre-written cover letter story that best matches "
    "this job description. Choose one label from the catalog below verbatim -- do not "
    "edit, rephrase, merge, or invent."
)
IMPACT_INSTRUCTION = (
    "You are selecting exactly ONE pre-written cover letter forward-looking impact "
    "statement that best matches this job description. Choose one label from the "
    "catalog below verbatim -- do not edit, rephrase, merge, or invent."
)
GRATITUDE_INSTRUCTION = (
    "You are selecting exactly ONE pre-written cover letter closing/gratitude "
    "paragraph that best matches this job description. Choose one label from the "
    "catalog below verbatim -- do not edit, rephrase, merge, or invent."
)


# ---------------------------------------------------------------------------
# Branch B, pass 1: heading selection.
#
# GOTCHA (carried over from the handoff, do not "simplify" this away):
# this branch falls back to the FULL heading catalog on zero valid
# selections, not to a single first entry like the 5 variant branches
# above. n8n's reasoning (from its own console.warn message): an empty
# Experience section is worse than an unfiltered one. Don't reuse
# select_variant() here — the fallback shape is genuinely different.
# ---------------------------------------------------------------------------

HEADING_INSTRUCTION = (
    "You are selecting which Professional Experience headings are relevant to this "
    "job description. You may select headings from different resume flavors (e.g. an "
    "AI role and an LC-MS role can both draw headings) -- cross-flavor hybrid "
    "combinations are allowed and expected when justified. Select only from the exact "
    "heading catalog below, do not invent new headings."
)


def select_headings(
    llm: LLMClient,
    role: str,
    job_description: str,
    heading_payloads: list[dict],
    branch_name: str = "heading pass 1",
    think: bool = False,
    critique_feedback: str | None = None,
    stability: str = "balanced",
) -> list[str]:
    """heading_payloads come from
    qdrant.fetch_by_section_type('professional_experience_heading').
    Each payload has a 'heading' field (the catalog entry's display text
    per seed_qdrant.js — heading records embed on the heading name itself).

    Returns the selected heading list, OR the full catalog if the model's
    selection didn't exact-match anything valid.

    think: see select_variant()'s docstring -- same parity-debugging
    finding applies to every branch, not just the variant-select ones.

    critique_feedback: see select_variant()'s docstring -- same
    no-op-when-None contract.
    """
    headings = [p.get("heading", "") for p in heading_payloads]
    catalog_text = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headings))

    prompt = (
        f"{HEADING_INSTRUCTION} "
        'Respond with ONLY valid JSON, no markdown code fences, no other text, '
        'in this exact shape: {"selected_headings": ["<heading>", ...]}.'
        f"\n\nJob description:\n{job_description}"
        f"\n\nHeading catalog:\n{catalog_text}"
    )
    if critique_feedback:
        prompt += (
            f"\n\nA prior draft using this catalog was reviewed and received this "
            f"feedback -- consider it when choosing which headings to include:\n{critique_feedback}"
            f"{_stability_suffix(stability)}"
        )

    response = llm.complete(role, [{"role": "user", "content": prompt}], think=think, json_mode=True)
    logger.debug("[%s] raw response: %r", branch_name, response.text)
    parsed = parse_json_response(response.text, default={"selected_headings": []})

    chosen = parsed.get("selected_headings")
    chosen = chosen if isinstance(chosen, list) else []

    valid = [h for h in chosen if h in headings]
    invalid = [h for h in chosen if h not in headings]

    if invalid:
        logger.warning(
            "[%s] heading(s) not in catalog, dropped: %s. Valid catalog: %s",
            branch_name, invalid, headings,
        )

    if not valid:
        logger.warning(
            "[%s] no valid headings selected — falling back to full catalog to "
            "avoid an empty Experience section.",
            branch_name,
        )
        return headings

    return valid


# ---------------------------------------------------------------------------
# Branch B, pass 2: bullet selection within the selected headings.
#
# GOTCHA: unlike headings, there is NO fallback here. An invalid bullet
# (doesn't exact-match the catalog for its heading) is just dropped,
# silently reducing that heading's bullet list — potentially to zero,
# in which case the heading itself doesn't appear in tailored_bullets at
# all (matches n8n: `if (valid.length > 0)` gates whether the heading is
# emitted).
# ---------------------------------------------------------------------------

BULLET_INSTRUCTION = (
    "You are selecting the most relevant bullets under each Professional Experience "
    "heading below, for this job description. Copy selected bullets VERBATIM -- do "
    "not edit, merge, rephrase, or invent new bullets. You do not need to select "
    "bullets from every heading -- but every heading listed below MUST still appear "
    "as a key in your JSON response. If you don't want any bullets from a heading, "
    "give it an empty array, e.g. \"Some Heading\": []. Never omit a heading's key "
    "entirely -- a heading present with an empty array means 'no relevant bullets'; "
    "a missing key is not a valid way to express that."
)


@dataclass
class BulletSelection:
    validated_selection: dict[str, list[str]] = field(default_factory=dict)
    tailored_bullets: str = ""  # assembled "### Heading\n- bullet\n- bullet" markdown


def select_bullets(
    llm: LLMClient,
    role: str,
    job_description: str,
    selected_headings: list[str],
    bullet_payloads: list[dict],
    branch_name: str = "bullet pass 2",
    think: bool = False,
    critique_feedback: str | None = None,
    stability: str = "balanced",
) -> BulletSelection:
    """bullet_payloads come from
    qdrant.fetch_by_section_type('professional_experience_bullet',
    extra_filter={'key': 'heading', 'match': {'any': selected_headings}}) —
    i.e. already restricted to the headings select_headings() picked.
    Each payload has 'heading' + 'text'.

    think: see select_variant()'s docstring.

    critique_feedback: see select_variant()'s docstring -- same
    no-op-when-None contract. Particularly relevant here since Critic's
    "Weak Bullets" section speaks directly to this branch's output.
    """
    grouped: dict[str, list[str]] = {}
    for p in bullet_payloads:
        grouped.setdefault(p.get("heading", ""), []).append(p.get("text", ""))

    catalog_text = ""
    for heading in selected_headings:
        bullets = grouped.get(heading, [])
        catalog_text += f"### {heading}\n"
        for i, b in enumerate(bullets):
            catalog_text += f"{i + 1}. {b}\n"
        catalog_text += "\n"

    prompt = (
        f"{BULLET_INSTRUCTION} "
        'Respond with ONLY valid JSON, no markdown code fences, no other text, in '
        'this exact shape (one key per heading listed below, no headings omitted): '
        '{"selected_bullets": { "<heading>": ["<verbatim bullet text>", ...], '
        '"<heading with nothing relevant>": [] } }.'
        f"\n\nJob description:\n{job_description}"
        f"\n\nBullets by heading:\n{catalog_text}"
    )
    if critique_feedback:
        prompt += (
            f"\n\nA prior draft using this catalog was reviewed and received this "
            f"feedback -- consider it, and select different bullets than before where "
            f"the feedback flags a bullet as weak or missing relevant keywords:\n{critique_feedback}"
            f"{_stability_suffix(stability)}"
        )

    response = llm.complete(role, [{"role": "user", "content": prompt}], think=think, json_mode=True)
    logger.debug("[%s] raw response: %r", branch_name, response.text)
    parsed = parse_json_response(response.text, default={"selected_bullets": {}})

    chosen = parsed.get("selected_bullets")
    chosen = chosen if isinstance(chosen, dict) else {}

    tailored_bullets = ""
    validated_selection: dict[str, list[str]] = {}

    for heading in selected_headings:
        catalog_bullets = grouped.get(heading, [])
        heading_key_present = heading in chosen
        picks = chosen.get(heading)
        picks = picks if isinstance(picks, list) else []

        valid = [b for b in picks if any(cb.strip() == str(b).strip() for cb in catalog_bullets)]
        invalid = [b for b in picks if not any(cb.strip() == str(b).strip() for cb in catalog_bullets)]

        if invalid:
            logger.warning(
                "[%s] %d bullet(s) under %r did not exact-match the catalog and "
                "were dropped: %s",
                branch_name, len(invalid), heading, invalid,
            )

        # These two cases used to log as one identical "0 were selected"
        # message, which made it impossible to tell apart (without
        # --debug) whether the model genuinely judged this heading
        # irrelevant -- which the prompt explicitly permits ("You do not
        # need to select from every heading") -- versus the heading's
        # own key silently not matching between select_headings()'s
        # output and this call's JSON response (e.g. a dropped "&",
        # reworded punctuation, stray whitespace), which is a real bug
        # rather than a model judgment call. Splitting them so the two
        # failure modes are distinguishable from the warning text alone.
        if not valid and catalog_bullets:
            if not heading_key_present:
                logger.warning(
                    "[%s] heading %r had %d catalog bullet(s) available, but its "
                    "key did not appear at all in the model's JSON response. Real "
                    "heading-string mismatches (altered punctuation, quotes, "
                    "whitespace) were ruled out via --debug on 2026-08-07 -- the "
                    "model was omitting the key wholesale even when the heading "
                    "string matched the catalog exactly elsewhere in the same "
                    "response. BULLET_INSTRUCTION now explicitly requires every "
                    "heading to appear as a key (empty array if nothing selected) "
                    "to close that ambiguity -- if this still fires after that "
                    "change, it's likely output-length/attention degradation on "
                    "later headings in a single large completion, not a prompt- "
                    "wording issue; consider splitting select_bullets() into one "
                    "call per heading if this persists. Run with --debug to see "
                    "the raw response.",
                    branch_name, heading, len(catalog_bullets),
                )
            else:
                logger.warning(
                    "[%s] heading %r had %d catalog bullet(s) available, its key "
                    "was present in the model's JSON response, but the model "
                    "selected 0 of them -- this heading will be omitted from "
                    "the resume. This may be a legitimate relevance judgment "
                    "(the prompt permits skipping a heading's bullets) rather "
                    "than a bug; if it looks wrong, run with --debug to see "
                    "the model's actual picks for this heading.",
                    branch_name, heading, len(catalog_bullets),
                )

        if valid:
            validated_selection[heading] = valid
            bullet_lines = "\n".join(f"- {b}" for b in valid)
            tailored_bullets += f"### {heading}\n{bullet_lines}\n\n"

    return BulletSelection(validated_selection=validated_selection, tailored_bullets=tailored_bullets.strip())


# ---------------------------------------------------------------------------
# Branch C: skills selection.
#
# Same "drop invalid, no fallback" shape as bullets, but flat — no
# heading grouping, just one catalog of atomic skill strings.
# ---------------------------------------------------------------------------

SKILLS_INSTRUCTION = (
    "You are selecting the individual Key Skills bullets most relevant to this job "
    "description, from the flat catalog below. Copy selected items VERBATIM -- do "
    "not edit, merge, or invent. Do not pull in unrelated skills just because they "
    "share a category with a relevant one."
)


@dataclass
class SkillsSelection:
    validated_selection: list[str] = field(default_factory=list)
    tailored_skills: str = ""  # "- skill\n- skill" markdown


def select_skills(
    llm: LLMClient,
    role: str,
    job_description: str,
    skill_payloads: list[dict],
    branch_name: str = "skills",
    think: bool = False,
    critique_feedback: str | None = None,
    stability: str = "balanced",
) -> SkillsSelection:
    """skill_payloads come from
    qdrant.fetch_by_section_type('key_skills'). Each payload has 'text'
    (one atomic skill bullet each, per seed_qdrant.js).

    think: see select_variant()'s docstring -- this is the exact branch
    the 2026-08-05 parity debugging session used to isolate the
    endpoint/think findings, so its default matters most here.

    critique_feedback: see select_variant()'s docstring -- same
    no-op-when-None contract. Particularly relevant here since Critic's
    "ATS & Keyword Coverage" section (missing keywords) speaks directly
    to this branch's output.
    """
    skills = [p.get("text", "") for p in skill_payloads]
    catalog_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(skills))

    prompt = (
        f"{SKILLS_INSTRUCTION} "
        'Respond with ONLY valid JSON, no markdown code fences, no other text, '
        'in this exact shape: {"selected_skills": ["<verbatim skill text>", ...]}.'
        f"\n\nJob description:\n{job_description}"
        f"\n\nSkills catalog:\n{catalog_text}"
    )
    if critique_feedback:
        prompt += (
            f"\n\nA prior draft using this catalog was reviewed and received this "
            f"feedback -- consider it, and select different/additional skills than "
            f"before where the feedback flags missing keywords:\n{critique_feedback}"
            f"{_stability_suffix(stability)}"
        )

    response = llm.complete(role, [{"role": "user", "content": prompt}], think=think, json_mode=True)
    logger.debug("[%s] raw response: %r", branch_name, response.text)
    parsed = parse_json_response(response.text, default={"selected_skills": []})

    chosen = parsed.get("selected_skills")
    chosen = chosen if isinstance(chosen, list) else []

    valid = [s for s in chosen if any(cs.strip() == str(s).strip() for cs in skills)]
    invalid = [s for s in chosen if not any(cs.strip() == str(s).strip() for cs in skills)]

    if invalid:
        logger.warning(
            "[%s] %d skill(s) did not exact-match the catalog and were dropped: %s",
            branch_name, len(invalid), invalid,
        )

    if not valid and skills:
        logger.warning(
            "[%s] %d catalog skill(s) available but 0 were selected -- Key Skills "
            "section will be empty.",
            branch_name, len(skills),
        )

    tailored_skills = "\n".join(f"- {s}" for s in valid)
    return SkillsSelection(validated_selection=valid, tailored_skills=tailored_skills)


# ---------------------------------------------------------------------------
# Always-full sections: no LLM call at all, just fetch + reshape.
# ---------------------------------------------------------------------------

# section_type values as stored by seed_qdrant.js. Note "honors" here vs.
# "honors_and_special_awards" in Qdrant — same mismatch n8n's own code
# carried (bySection.honors_and_special_awards, exposed as `honors`).
ALWAYS_FULL_SECTION_TYPES = [
    "career_history",
    "education",
    "patents",
    "honors_and_special_awards",
    "publications",
]


@dataclass
class AlwaysFullSections:
    career_history: str = ""
    education: str = ""
    patents: str = ""
    honors: str = ""
    publications: str = ""


def load_always_full_sections(payloads: list[dict]) -> AlwaysFullSections:
    """payloads come from
    qdrant.fetch_by_section_type(ALWAYS_FULL_SECTION_TYPES). Each of the
    5 sections is stored as one point with payload {section_type, text}
    (not chunked, per seed_qdrant.js's 'always_full'/'conditional_full'
    selection_mode).

    Note: publications is 'conditional_full' in seed_qdrant.js (meant to
    skip for non-publishing-heavy roles), but per the n8n export's own
    comment, that skip gate was never built — it defaults to included
    here too, matching the documented default-include behavior rather
    than silently adding a filter n8n never had.
    """
    by_section = {p.get("section_type"): p.get("text", "") for p in payloads}
    return AlwaysFullSections(
        career_history=by_section.get("career_history", ""),
        education=by_section.get("education", ""),
        patents=by_section.get("patents", ""),
        honors=by_section.get("honors_and_special_awards", ""),
        publications=by_section.get("publications", ""),
    )


# ---------------------------------------------------------------------------
# Cover-letter stitch pass ("edit cover letter" in the n8n export).
#
# One more LLMClient call over the merged intro/story/impact/gratitude
# selections — light-edit only (insert job title/company name, smooth
# transitions, trim redundancy), explicitly forbidden from inventing new
# facts. Prompt ported verbatim from the export.
# ---------------------------------------------------------------------------


def stitch_cover_letter(
    llm: LLMClient,
    role: str,
    job_title: str,
    company_name: str,
    job_description: str,
    intro: VariantSelection,
    story: VariantSelection,
    impact: VariantSelection,
    gratitude: VariantSelection,
    think: bool = False,
    critique_feedback: str | None = None,
    stability: str = "balanced",
) -> str:
    """think: see select_variant()'s docstring.

    critique_feedback: see select_variant()'s docstring -- same
    no-op-when-None contract. This branch can only act on feedback via
    its existing light-edit powers (transitions, trimming, placeholder
    fill) -- it still cannot invent facts, so feedback calling for a
    genuinely different story/impact/intro should be addressed by
    re-running select_variant() for that section, not by leaning on
    this pass to fix it via rewriting.

    stability: see select_variant()'s docstring. Note this branch is
    usually SKIPPED entirely on revision rounds where intro/story/
    impact/gratitude didn't change from the prior round (see writer.py's
    generate_draft()) -- when it does run, "strict" asks it to touch as
    little wording as possible beyond the placeholder fills it already
    only ever does, "loose" gives it more latitude on transitions/tone.
    """
    prompt = (
        "You are lightly editing four pre-selected cover letter sections into one "
        "flowing letter.\n"
        "Do NOT invent new facts, employers, metrics, or accomplishments. You may "
        "only: insert the job title\n"
        "and company name where placeholders appear, smooth transitions between "
        "sections, and trim redundancy\n"
        "between the Introduction and Alignment text below. Do not remove or "
        "reorder the four sections.\n\n"
        f"Job Title: {job_title or '[Job Title]'}\n"
        f"Company Name: {company_name}\n"
        f"Job Description:\n{job_description}\n\n"
        f"1. INTRODUCTION (verbatim selection):\n{intro.text}\n\n"
        "Supporting alignment framing (verbatim selection, weave in naturally, "
        f"don't duplicate the Introduction):\n{intro.alignment_text}\n\n"
        f"2. DETAILED STORY (verbatim selection):\n{story.text}\n\n"
        f"3. FORWARD-LOOKING IMPACT (verbatim selection):\n{impact.text}\n\n"
        f"4. CLOSING (verbatim selection):\n{gratitude.text}\n\n"
        "Replace [Job Title] and [Company Name] placeholders throughout with the "
        "values given above.\n"
        "Respond with ONLY the final letter text, no preamble, no markdown fences, "
        "no section labels."
    )
    if critique_feedback:
        prompt += (
            f"\n\nA prior version of this letter was reviewed and received this "
            f"feedback -- address what you can within the light-edit constraints "
            f"above (tone, transitions, redundancy), without inventing new facts:"
            f"\n{critique_feedback}"
            f"{_stability_suffix(stability)}"
        )

    response = llm.complete(role, [{"role": "user", "content": prompt}], think=think)
    logger.debug("[stitch] raw response: %r", response.text)
    text = response.text.strip()

    # DEFENSIVE: seen in practice (2026-08-06, Guardant Health run) -- despite
    # "Respond with ONLY the final letter text, no preamble," the model
    # sometimes prefixes its own meta-commentary ("Okay, here's the final
    # letter text after addressing those points...") before the actual
    # letter. If the response doesn't already open on a salutation line but
    # contains one further down, cut everything before it. This is a
    # narrow, letter-specific heuristic (cover letters conventionally open
    # "Dear ...") -- it does not invent or alter any content, only trims a
    # preamble the model was explicitly told not to produce.
    if not re.match(r"^\s*Dear\b", text, re.IGNORECASE):
        salutation = re.search(r"^\s*Dear\b.*$", text, re.IGNORECASE | re.MULTILINE)
        if salutation:
            logger.warning(
                "[stitch] response had a leading preamble before the salutation "
                "-- trimmed it: %r",
                text[:salutation.start()].strip(),
            )
            text = text[salutation.start():].strip()

    return text


# ---------------------------------------------------------------------------
# Final assembly ("assemble draft resume" in the n8n export). Pure Python
# string building, no LLM call.
# ---------------------------------------------------------------------------


@dataclass
class DraftResume:
    tailored_summary: str
    tailored_bullets: str
    cover_letter: str


def assemble_draft(
    summary_text: str,
    bullets_markdown: str,
    skills_markdown: str,
    always: AlwaysFullSections,
    cover_letter: str,
) -> DraftResume:
    tailored_bullets = (
        f"## Career History\n{always.career_history}\n\n"
        f"## Professional Experience\n{bullets_markdown}\n\n"
        f"## Key Skills\n{skills_markdown}\n\n"
        f"## Education\n{always.education}\n\n"
        f"## Selected Publications\n{always.publications}\n\n"
        f"## Patents\n{always.patents}\n\n"
        f"## Honors and Special Awards\n{always.honors}"
    )
    return DraftResume(
        tailored_summary=summary_text,
        tailored_bullets=tailored_bullets,
        cover_letter=cover_letter,
    )
