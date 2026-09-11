"""
humanizer.py -- Writer subsystem step 6 (refined from "local-LLM
proofreader" to "humanizer", per the 2026-09-09 refinement session).

Takes one section's current text (summary / bullets / cover letter) and
asks a local model to smooth AI-generated rhythm/phrasing tells --
repetitive bullet openers, uniform sentence length, empty inflated
modifiers ("dynamic," "results-driven" with no metric attached),
mirrored clause structure -- WITHOUT touching facts, numbers, dates, or
exact terminology that overlaps the job description. This is a fluency
pass, not a rewrite: still formal, still positive, just less
statistically uniform.

Like diff.py/critic.py/revision.py, this module is persistence-agnostic
and UI-agnostic: it takes text in, returns proposed text out, no
printing, no storage, no diffing. dashboard.py's propose route (Phase D)
is what calls diff.word_diff_hunks() on the before/after pair to build
the accept/reject UI; this module doesn't know that UI exists.

Never auto-applies anything -- this module doesn't touch final_edit or
any other table. Same propose-then-approve boundary as Filler/the
ATS-adapter wizard: producing a suggestion and applying one are two
different, deliberately separated actions.
"""
from __future__ import annotations

from .llm import LLMClient

# Section-specific instruction. tailored_bullets gets the strictest
# version -- bullets are short and keyword-dense (this is where a
# recruiter's or ATS's exact-term matching does the most work), so the
# model is told to touch ONLY the leading verb/connective words and
# leave every noun phrase (skills, tools, technologies, certifications)
# untouched. tailored_summary and cover_letter are prose paragraphs and
# get more room to vary sentence rhythm, still under the same
# don't-paraphrase-JD-terms and don't-add-or-remove-substance rules.
_SECTION_INSTRUCTIONS: dict[str, str] = {
    "tailored_summary": (
        "This is a resume summary paragraph. Smooth its rhythm so it reads "
        "like a careful human wrote it, not a template: vary sentence "
        "length, avoid starting consecutive sentences with the same "
        "structure, cut inflated modifiers that carry no concrete meaning "
        "(e.g. \"dynamic,\" \"passionate,\" \"results-driven\") unless a "
        "specific number or outcome backs them up. Do not add or remove any "
        "claim, skill, or fact. Keep it formal and positive in tone -- this "
        "is a fluency pass, not a tone change."
    ),
    "tailored_bullets": (
        "These are resume bullet points, one per line. Vary ONLY the "
        "leading verb and connective phrasing across bullets so they don't "
        "all follow the identical pattern (e.g. not every bullet starting "
        "with \"Led\" or \"Spearheaded\"). Do NOT touch any noun phrase -- "
        "skills, tools, technologies, certifications, team/company names, "
        "or any number/metric must appear byte-for-byte unchanged. Do not "
        "merge, split, add, or remove bullets. Keep every bullet formal and "
        "achievement-oriented."
    ),
    "cover_letter": (
        "This is a cover letter. Smooth its rhythm so it reads like a "
        "careful human wrote it, not a template: vary sentence length and "
        "structure across paragraphs, cut inflated modifiers that carry no "
        "concrete meaning unless backed by a specific example, avoid "
        "mirrored/parallel clause structure repeated across consecutive "
        "sentences. Do not add or remove any claim, fact, or example. Keep "
        "it formal and positive -- this is a fluency pass, not a tone "
        "change or a persuasion rewrite."
    ),
}

_SYSTEM_PROMPT = """You are a careful copy editor for job-application materials (resumes and cover letters). Your ONLY job is to reduce AI-generated writing tells -- repetitive sentence patterns, uniform rhythm, empty inflated language -- while leaving the substance completely untouched.

Hard rules, no exceptions:
1. Never invent, add, or remove a claim, skill, achievement, number, date, or fact.
2. Never paraphrase a term that appears in the job description below -- if the posting uses an exact phrase (a tool, skill, certification, or methodology name), your output must use that exact phrase too, verbatim.
3. Stay within roughly the original's word count -- do not pad or compress meaningfully.
4. Keep the tone formal and positive. You are not making this more casual, funnier, or more persuasive -- only less statistically repetitive.
5. Output ONLY the rewritten text for the section given. No preamble, no explanation, no markdown fences, no commentary.

Job description this material is tailored to (for terminology reference only -- do not summarize or reference it directly, just avoid paraphrasing away any of its exact terms):
{job_description}
"""


def humanize_section(
    text: str,
    section_key: str,
    job_description: str,
    llm: LLMClient,
    *,
    role: str = "writer_humanizer",
    timeout: int = 600,
) -> str:
    """Runs one section's current text through the humanizer role and
    returns the proposed rewrite as plain text. Does not diff, does not
    persist, does not decide accept/reject -- callers (dashboard.py's
    propose route) own all of that.

    section_key must be one of _SECTION_INSTRUCTIONS's keys (the three
    WriterDraft/final_edit fields this project already treats as
    independent -- same three diff.py diffs section-by-section). Raises
    KeyError for anything else rather than guessing an instruction,
    matching LLMClient.complete()'s own "unknown role -> KeyError" norm
    for roles.yaml.

    Empty/whitespace-only text is returned unchanged without calling the
    model -- there is nothing to humanize in an empty section, and an
    empty-input call would just waste a round trip for no reason.
    """
    if section_key not in _SECTION_INSTRUCTIONS:
        raise KeyError(
            f"no humanizer instruction for section '{section_key}' -- "
            f"expected one of {sorted(_SECTION_INSTRUCTIONS)}"
        )

    if not text or not text.strip():
        return text

    system = _SYSTEM_PROMPT.format(job_description=job_description or "(not provided)")
    instruction = _SECTION_INSTRUCTIONS[section_key]

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{instruction}\n\n---\n{text}"},
    ]

    # think=False explicitly -- unlike selection.py/writer.py (which pass
    # `think` deliberately, see OllamaNativeClient.chat()'s docstring),
    # this call never set it at all, leaving Ollama at its own default
    # for this model. A live timeout on real bullets content (2026-09-11)
    # is consistent with silent default-on thinking mode: a rules-based
    # fluency pass gets no value from deliberation, so it's turned off
    # explicitly rather than left ambiguous.
    #
    # timeout raised to 600s (from OllamaNativeClient's already-raised
    # 300s default -- see that class's own docstring on why 300 was
    # chosen) as a second line of defense: even with thinking off, a 12B
    # local model rewriting a real multi-entry bullets section is
    # legitimately slower than the synthetic 3-bullet smoke test this
    # role was first verified against.
    response = llm.complete(role, messages, think=False, timeout=timeout)
    return response.text.strip()
