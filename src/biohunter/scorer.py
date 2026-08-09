"""Scorer agent: one blind-judgment LLM call producing a job-FIT score
(postings.score / postings.score_rationale) for a posting BEFORE any
resume gets generated for it -- the "which of these 693 postings are
worth generating for" triage step the 2026-08-09 handoff calls out as a
separate, real piece of work from Critic's resume-QUALITY score
(drafts.final_score). Per the pipeline diagram (Scout -> Scorer -> Writer
-> Critic -> Human Review), this is the step that's been missing.

Deliberately NOT the same shape as critic.py's critique_draft(): Critic
judges an already-written draft against a job description. Scorer judges
a job POSTING against the CANDIDATE -- their existing summary/skills/
career-history/education catalog (the same Qdrant `resume_content`
collection Writer draws from, via qdrant.py + selection.py's own catalog
helpers) plus their stated location/title preferences
(config/search_criteria.yaml) -- with no draft anywhere in the loop. Same
"one prompt, one call, return structured text" spirit as critic.py,
though: there's nothing to SELECT here (no verbatim-choice constraint
selection.py's branches enforce), just a judgment to make, so it reuses
critic.py's own ScoreResult / parse_score() rather than inventing a
second "SCORE: N -- rationale" parser that has to be kept in sync with
the first.

CORRECTED against real source (writer.py/selection.py/qdrant.py, added
2026-08-09 after this module's first draft was written blind against an
AST outline only):
  - section_type values are "professional_summary" and "key_skills", not
    "summary"/"skills" -- the first draft's guessed names would have
    returned zero Qdrant points every time, silently, since
    fetch_by_section_type() has no fallback and no error on an empty
    match.
  - key_skills payloads carry only `text` (see select_skills() in
    selection.py) -- no `label` field, unlike the professional_summary
    catalog. Running them through load_catalog()/CatalogEntry the same
    way as the summary catalog produced blank labels; skills are now
    read as a flat text list instead, matching select_skills()'s own
    approach.
  - llm.complete() takes `think` as a required-in-spirit kwarg -- per
    selection.py's own docstring, omitting it does NOT behave like
    think=False, it runs 4-6x slower like think=True. The first draft
    omitted it entirely. Fixed: score_posting() now takes `think` and
    always passes it through explicitly, same convention every other
    LLM-calling function in this codebase follows.

SCOPE LIMIT, stated explicitly rather than solved by omission (per this
project's own working style -- see the 2026-08-09 handoff's "Scorer vs
Critic score" section): schema.sql's own postings.score comment describes
fit to "the candidate, location, seniority, visa, salary, preferences."
Visa status and salary expectations are NOT modeled anywhere in this
codebase today -- not in search_criteria.yaml, not in Qdrant, not in any
config file. This version scores fit on role/skill/background alignment
(semantic, against the candidate's Qdrant catalog), location (against
search_criteria.yaml's location_include/exclude), and seniority (inferred
from title/description text). Visa and salary are NOT scored -- there is
no data to score them against yet. If those matter, they need a real new
config field (most likely a search_criteria.yaml addition) before Scorer
can use them; not guessed here.

CONFIG DEPENDENCY, confirmed against real roles.yaml: no `scorer_fit`
entry exists yet. LLMClient resolves role names purely from
config/roles.yaml, so this will fail with a lookup error until one is
added. Every existing role in your roles.yaml routes through Ollama
(gemma4:12b-mlx or qwen2.5:14b) except the still-unused mlx_smoke_test --
there is no cloud-routed role active in this file to mirror for a
"quality-sensitive" default the way the earlier draft assumed. Suggested
addition, consistent with your file's own local-first pattern (add to
config/roles.yaml, not done here since it's your file to own):

    scorer_fit:
      provider: ollama
      model: qwen2.5:14b       # matches scout_summarizer's model -- a
                                # cheap/fast local model is appropriate
                                # here, this runs once per posting at
                                # triage scale (hundreds of calls)
      base_url: http://localhost:11434

INVOCATION, scoped deliberately: like run_scout(), this is driven from the
CLI (`biohunter score-postings`), not from the dashboard. The dashboard
only reads and filters/sorts on the postings.score column this populates
-- it does not trigger scoring itself, matching the existing precedent
that Scout also only ever runs from the CLI, never from a dashboard
button.
"""
from __future__ import annotations

from . import qdrant
from .config import SearchCriteria
from .critic import ScoreResult, parse_score
from .llm import LLMClient
from .selection import (
    ALWAYS_FULL_SECTION_TYPES,
    load_always_full_sections,
    load_catalog,
)

SCORER_ROLE = "scorer_fit"

SCORER_INSTRUCTION = (
    "You are a candid, detail-oriented career advisor helping a candidate triage a "
    "large batch of job postings BEFORE they spend time generating a tailored resume "
    "for any of them. You are given the candidate's actual background (summary, "
    "skills, career history, education) and their stated location/title preferences, "
    "plus one job posting. Your job is to judge how good a FIT this posting is for "
    "this candidate -- NOT how good a resume could be written for it (that is a "
    "separate, later step). Be direct: a senior-only posting for a candidate with no "
    "matching seniority, or a posting far outside stated location preferences, should "
    "score low even if the subject-matter skills overlap well.\n\n"
    "Consider, in this order of importance: (1) role/skill/background alignment "
    "against the candidate's actual profile below -- don't assume relevance from the "
    "job title alone; (2) location fit against the candidate's stated preferences; "
    "(3) seniority fit (junior/mid/senior/staff+) based on the posting's title and "
    "description.\n\n"
    "Do NOT attempt to judge visa sponsorship or salary fit -- you have no data on "
    "either for this candidate; ignore those dimensions entirely rather than "
    "guessing.\n\n"
    "Respond with your assessment as one short paragraph, then end with exactly this "
    "line and nothing after it:\n"
    "SCORE: <integer 1-10> -- <one-sentence rationale>"
)


def _build_candidate_profile_text() -> str:
    """Fetches the candidate's summary/skills/career-history/education
    from Qdrant and flattens them into one plain-text block for the
    prompt. Uses each section_type's own established shape rather than
    a single generic load -- professional_summary is a catalog (label +
    text, per select_variant()'s branch), key_skills is a flat list of
    atomic strings (per select_skills()'s branch, no label field), and
    career_history/education are single always-full text blocks (per
    load_always_full_sections()). Reusing three different existing
    readers, rather than inventing one Scorer-specific fourth shape.
    """
    summary_catalog = load_catalog(qdrant.fetch_by_section_type("professional_summary", limit=20))
    summary_text = "\n".join(f"- {c.label}: {c.text}" for c in summary_catalog) or "(none found)"

    skill_payloads = qdrant.fetch_by_section_type("key_skills", limit=100)
    skills_text = "\n".join(f"- {p.get('text', '')}" for p in skill_payloads) or "(none found)"

    always_payloads = qdrant.fetch_by_section_type(
        [t for t in ALWAYS_FULL_SECTION_TYPES if t in ("career_history", "education")], limit=20
    )
    always = load_always_full_sections(always_payloads)

    return (
        f"SUMMARY OPTIONS ON FILE:\n{summary_text}\n\n"
        f"KEY SKILLS ON FILE:\n{skills_text}\n\n"
        f"CAREER HISTORY:\n{always.career_history or '(none found)'}\n\n"
        f"EDUCATION:\n{always.education or '(none found)'}"
    )


def score_posting(
    llm: LLMClient,
    company_name: str,
    job_title: str,
    location: str | None,
    job_description: str,
    criteria: SearchCriteria,
    think: bool = False,
) -> ScoreResult:
    """One blind fit-judgment call for one posting. Returns critic.py's
    ScoreResult (score: int | None, rationale: str | None) -- reused as-is
    rather than duplicated, since the output shape (and the SCORE: line
    format parse_score() expects) is identical to Critic's.

    think: forwarded to llm.complete() exactly like every selection.py
    branch does -- per that module's own documented gotcha, never omit
    this, omitting it does not behave like think=False. Default False
    matches every other LLM call in this codebase's own default.
    """
    profile_text = _build_candidate_profile_text()

    location_pref = ", ".join(criteria.location_include) if criteria.location_include else "no location preference stated"
    location_avoid = ", ".join(criteria.location_exclude) if criteria.location_exclude else "none stated"
    title_pref = ", ".join(criteria.title_include) if criteria.title_include else "no title-keyword preference stated"

    prompt = f"""{SCORER_INSTRUCTION}

CANDIDATE PROFILE:
{profile_text}

CANDIDATE STATED PREFERENCES (search_criteria.yaml):
- Preferred locations: {location_pref}
- Locations to avoid: {location_avoid}
- Preferred title keywords: {title_pref}

JOB POSTING:
Company: {company_name}
Title: {job_title}
Location: {location or 'not specified'}
Description:
{job_description}
"""
    response = llm.complete(SCORER_ROLE, [{"role": "user", "content": prompt}], think=think)
    return parse_score(response.text)
