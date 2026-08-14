"""
Static HTML activity report for a single posting (ADR-0006 decision #3 /
ROADMAP Phase 2's `biohunter report` item), per the 2026-08-07 Diff-Score-
BulletFix handoff's "FIRST THING TO DO NEXT SESSION" list, item 3.

Scope of this pass, per explicit direction: single-posting report now,
a multi-posting index later. This module renders ONE posting's full
pipeline output -- Writer's draft, Critic's critique, the ATS score,
and the round-by-round revision history/diffs -- as one self-contained
HTML file. No server, no JS framework, no network fetch (fonts are the
system stack only -- see the `morning` skill's font gotcha for why that
matters in this sandbox; nothing here needs it anyway).

Like critic.py/revision.py/diff.py, this module is persistence-agnostic
and pure: render_posting_report() takes a RevisionResult (plus the
posting's own company/title/job description and optional round diffs)
and returns an HTML string. It does no file I/O and touches no DB --
cli.py's new `report` command owns writing the string to disk, matching
every other module's "pure functions in, dataclasses/strings out, the
CLI decides what to do with it" split.

Deliberately reuses data that already exists rather than adding new
data collection: RevisionResult (writer.py + critic.py, via
revision.py) and RoundDiff/SectionDiff (diff.py) already carry
everything this report needs. This is a rendering pass, same spirit as
diff.py's own docstring ("adds no new data").
"""
from __future__ import annotations

import datetime
import html
import re

from .critic import ScoreResult, parse_score
from .diff import RoundDiff, SectionDiff
from .revision import RevisionResult, RevisionRound

# ---------------------------------------------------------------------------
# Small text -> HTML helpers. Intentionally NOT a general markdown renderer
# -- the only markdown this project's own text ever produces is "## Heading"
# lines (assemble_draft()'s tailored_bullets, critic.py's six/seven fixed
# headers) and "- item" bullet lists (selection.py's tailored_skills,
# catalog bullets). Handling exactly that vocabulary, nothing more, avoids
# a markdown-library dependency for a shape this predictable -- and if a
# model ever emits something outside it, this degrades to a plain escaped
# paragraph rather than mangling it, same "degrade, don't crash" pattern as
# selection.py's parse_json_response.
# ---------------------------------------------------------------------------

_esc = html.escape

# Inline markdown this project's own text can plausibly contain within a
# paragraph/bullet line -- NOT a general markdown renderer (see the
# module docstring above), just the two emphasis forms a local model
# reaches for on its own even though nothing in this codebase's prompts
# asks it to (2026-08-13 handoff: literal "**"/"###" showing up in the
# PDF). Bold before italic so "**x**" doesn't get half-eaten by the
# italic pattern first (a lone "*" left over from a stripped "**" would
# otherwise pair with the next real "*" and italicize the wrong span).
# Order of operations: escape the raw text FIRST (so any "<"/">"/"&" a
# model emits is neutralized), then apply these on the already-escaped
# string -- "**"/"*" survive html.escape() untouched, so this is safe.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _render_inline_markdown(escaped_text: str) -> str:
    """Takes ALREADY-html.escape()'d text and converts **bold**/*italic*
    markers to <strong>/<em>. Never call this on unescaped text -- see
    _esc_inline() below, which is the one function every caller should
    actually use."""
    text = _BOLD_RE.sub(r"<strong>\1</strong>", escaped_text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def _esc_inline(text: str) -> str:
    """_esc() (html.escape) followed by inline-markdown conversion --
    the one function callers in this module should use for any text
    that will be displayed as part of a sentence (as opposed to _esc()
    alone, which is still correct for things like attribute values or
    headings where markdown emphasis wouldn't make sense)."""
    return _render_inline_markdown(_esc(text))


def _render_prose_block(text: str) -> str:
    """Blank-line-separated paragraphs, with '- ' runs collected into a
    <ul>. Everything is escaped before any markdown conversion -- this
    text can originate from a job posting, a local LLM, or a resume
    catalog, none of which are a trusted markup source. A stray '### '
    line inside a block (a nested sub-heading a model wasn't asked for,
    but sometimes produces anyway) is rendered as a small inline label
    rather than left as literal hash characters or promoted to a real
    <h3> that would visually compete with this report's own fixed
    section headings."""
    text = (text or "").strip()
    if not text:
        return '<p class="empty">(none)</p>'

    blocks = re.split(r"\n\s*\n", text)
    parts: list[str] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.startswith(("- ", "* ")) for ln in lines):
            items = "".join(f"<li>{_esc_inline(ln[2:].strip())}</li>" for ln in lines)
            parts.append(f"<ul>{items}</ul>")
        else:
            rendered_lines = []
            for ln in lines:
                sub_heading = re.match(r"^#{1,6}\s+(.+)$", ln)
                if sub_heading:
                    rendered_lines.append(f"<strong>{_esc_inline(sub_heading.group(1))}</strong>")
                else:
                    rendered_lines.append(_esc_inline(ln))
            # Preserve single line breaks within a paragraph (e.g. a
            # cover letter's salutation/signature lines) as <br>, since
            # collapsing them to one line would run "Dear Hiring
            # Manager," into the next sentence.
            parts.append(f"<p>{'<br>'.join(rendered_lines)}</p>")
    return "\n".join(parts) or '<p class="empty">(none)</p>'


def _split_headed_sections(text: str) -> list[tuple[str, str]]:
    """Splits text on '## Heading' lines into (heading, body) pairs.
    Used for both tailored_bullets (assemble_draft()'s fixed 7 headers)
    and critique text (critic.py's fixed 6-7 headers) -- same shape,
    one splitter. Text before the first '## ' (there shouldn't be any,
    but a model can surprise you) is returned under an empty heading so
    it isn't silently dropped."""
    text = text or ""
    pieces = re.split(r"(?m)^##\s+(.+?)\s*$", text)
    # re.split with a capturing group interleaves: [pre, head1, body1, head2, body2, ...]
    sections: list[tuple[str, str]] = []
    pre = pieces[0].strip()
    if pre:
        sections.append(("", pre))
    for i in range(1, len(pieces), 2):
        heading = pieces[i].strip()
        body = pieces[i + 1] if i + 1 < len(pieces) else ""
        sections.append((heading, body.strip()))
    return sections


def _score_bucket(score: int | None) -> str:
    """CSS class bucket for the score readout / badges. Thresholds are
    a display convenience only -- nothing here feeds back into
    revision.py's loop (see critic.py's ScoreResult docstring: display-
    only by design, no auto-stop logic exists to mirror)."""
    if score is None:
        return "unknown"
    if score >= 8:
        return "good"
    if score >= 5:
        return "mid"
    return "low"


def _slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip()).strip("-")
    return text.lower() or "untitled"


def report_id(company_name: str, job_title: str, when: datetime.datetime | None = None) -> str:
    """Deterministic-enough ID for a single report, used as both the
    on-page 'REPORT ID' readout and (by cli.py) the output filename.
    Not a database key -- this project has no `awaiting_review`/report
    persistence yet (see ROADMAP), so this is just a stable label, not
    a uniqueness guarantee across re-runs of the same posting on the
    same day."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    return f"{_slug(company_name)}_{_slug(job_title)}_{when.strftime('%Y%m%d-%H%M')}"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_score_dial(score_result: ScoreResult, label: str) -> str:
    bucket = _score_bucket(score_result.score)
    value = str(score_result.score) if score_result.score is not None else "?"
    rationale = _esc_inline(score_result.rationale) if score_result.rationale else "Score did not parse from the critique."
    return (
        f'<div class="dial dial--{bucket}">'
        f'<div class="dial__value">{value}<span class="dial__max">/10</span></div>'
        f'<div class="dial__label">{_esc(label)}</div>'
        f'</div>'
        f'<p class="dial__rationale">{rationale}</p>'
    )


def _render_draft_panel(number: str, title: str, body_html: str) -> str:
    return (
        f'<section class="panel">'
        f'<div class="panel__eyebrow">{_esc(number)}</div>'
        f'<h2 class="panel__title">{_esc(title)}</h2>'
        f'<div class="panel__body">{body_html}</div>'
        f'</section>'
    )


def _render_tailored_bullets(tailored_bullets: str) -> str:
    """tailored_bullets already contains its own '## Heading' structure
    (assemble_draft()) -- render each as a labelled sub-block rather
    than one undifferentiated blob, so Career History / Professional
    Experience / Key Skills / Education / Publications / Patents /
    Honors are each visually distinct, matching how verify-writer's
    CLI output already treats this as one section but this report can
    afford to do better since it isn't constrained to a terminal."""
    parts = []
    for heading, body in _split_headed_sections(tailored_bullets):
        if not heading:
            parts.append(_render_prose_block(body))
            continue
        parts.append(
            f'<div class="subsection"><h3>{_esc(heading)}</h3>{_render_prose_block(body)}</div>'
        )
    return "\n".join(parts)


_CRITIQUE_HEADER_ORDER = [
    "ATS & Keyword Coverage",
    "Unsupported Claims",
    "Weak Bullets",
    "Weak Summary",
    "Cover Letter Critique",
    "Overall Recommendation",
]


def _render_critique(critique_text: str) -> str:
    """Renders critic.py's six substantive headers as cards. The
    seventh header ('## Score') is deliberately excluded here -- it's
    already surfaced as the score dial above this panel via
    parse_score(), so repeating the raw SCORE line here would just be
    the same fact twice. Any header the model didn't produce (drift is
    a known issue for this local model -- see the 2026-08-07 handoff)
    is simply absent from the cards rather than shown empty; the raw
    critique text is still available in the "Full critique text"
    fallback below so nothing is lost to a formatting miss."""
    sections = dict(_split_headed_sections(critique_text))
    cards = []
    for header in _CRITIQUE_HEADER_ORDER:
        body = sections.get(header)
        if body is None:
            continue
        cards.append(
            f'<div class="subsection"><h3>{_esc(header)}</h3>{_render_prose_block(body)}</div>'
        )
    if not cards:
        # No recognized headers at all -- degrade to the raw text rather
        # than an empty panel (same "don't hide a formatting miss"
        # reasoning as parse_score()'s own warning).
        cards.append(_render_prose_block(critique_text))
    return "\n".join(cards)


def _render_diff_line(line: str) -> str:
    cls = "ctx"
    if line.startswith("+++") or line.startswith("---"):
        cls = "hdr"
    elif line.startswith("@@"):
        cls = "hunk"
    elif line.startswith("+"):
        cls = "add"
    elif line.startswith("-"):
        cls = "del"
    return f'<span class="diffline diffline--{cls}">{_esc(line)}</span>'


def _render_word_diff(word_ops: list[tuple[str, str]]) -> str:
    """Renders a word_ops list (see diff.py's _word_diff_ops()) as one
    wrapping paragraph with inline <ins>/<del> spans -- the prose
    counterpart to _render_diff_line()'s line-based +/- rendering.
    Unlike the line-diff view, this does NOT show both old and new as
    separate blocks; deletions and insertions are interleaved inline,
    in reading order, which is what actually makes a wording change
    scannable in a paragraph (the 2026-08-13 handoff's core complaint
    about the old line-diff view on prose)."""
    parts = []
    for tag, token in word_ops:
        escaped = _esc(token)
        if tag == "equal":
            parts.append(escaped)
        elif tag == "delete":
            parts.append(f'<del class="worddiff__del">{escaped}</del>')
        elif tag == "insert":
            parts.append(f'<ins class="worddiff__ins">{escaped}</ins>')
    return f'<p class="worddiff">{"".join(parts)}</p>'


def _render_section_diff(section: SectionDiff) -> str:
    if not section.changed:
        return (
            f'<div class="subsection"><h3>{_esc(section.section)}</h3>'
            f'<p class="empty">(unchanged)</p></div>'
        )
    if section.mode == "word":
        body = _render_word_diff(section.word_ops)
    else:
        lines = "\n".join(_render_diff_line(ln) for ln in section.diff_text.splitlines())
        body = f'<pre class="diff">{lines}</pre>'
    return f'<div class="subsection"><h3>{_esc(section.section)}</h3>{body}</div>'


def _render_round_history(rounds: list[RevisionRound], round_diffs: list[RoundDiff]) -> str:
    """One <details> block per round after the first, each showing that
    round's score + a collapsed-by-default diff against the round
    before it. The first round (round 0, the initial draft) has
    nothing to diff against, so it's summarized as the starting point
    rather than given its own empty diff block."""
    if not rounds:
        return '<p class="empty">No rounds recorded.</p>'

    blocks = []
    first = rounds[0]
    first_score = parse_score(first.critique)
    blocks.append(
        f'<div class="round round--base">'
        f'<div class="round__head">Round {first.round_number} &mdash; first draft'
        f'<span class="round__score round__score--{_score_bucket(first_score.score)}">'
        f'{first_score.score if first_score.score is not None else "?"}/10</span></div>'
        f'</div>'
    )

    diffs_by_round = {rd.round_to: rd for rd in round_diffs}
    for rnd in rounds[1:]:
        score = parse_score(rnd.critique)
        rd = diffs_by_round.get(rnd.round_number)
        diff_html = (
            "\n".join(_render_section_diff(sec) for sec in rd.sections)
            if rd is not None
            else '<p class="empty">No diff available for this round.</p>'
        )
        blocks.append(
            f'<details class="round">'
            f'<summary class="round__head">Round {rnd.round_number} &mdash; revision'
            f'<span class="round__score round__score--{_score_bucket(score.score)}">'
            f'{score.score if score.score is not None else "?"}/10</span></summary>'
            f'<div class="round__body">{diff_html}</div>'
            f'</details>'
        )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Top-level render
# ---------------------------------------------------------------------------

_STYLE = """
:root {
  --bg: #F6F7F5;
  --panel: #FFFFFF;
  --ink: #17231F;
  --ink-soft: #52625C;
  --ink-faint: #8B978F;
  --hairline: #DCE3DE;
  --accent: #0E6E58;
  --accent-soft: #E4F1EC;
  --good: #0E6E58;
  --good-bg: #E4F1EC;
  --mid: #B4780F;
  --mid-bg: #FBEED9;
  --low: #B0402A;
  --low-bg: #FBE3DC;
  --unknown: #8B978F;
  --unknown-bg: #EDEFEC;
  --mono: ui-monospace, "SF Mono", "Cascadia Code", "Roboto Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--sans);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 880px; margin: 0 auto; padding: 0 24px 96px; }

/* ---- Header band: lab-requisition styling, mono readout ---- */
.header {
  background: var(--ink);
  color: #F6F7F5;
  padding: 40px 24px 32px;
}
.header__inner { max-width: 880px; margin: 0 auto; }
.header__id {
  font-family: var(--mono);
  font-size: 12.5px;
  letter-spacing: 0.06em;
  color: #9FD6C2;
  text-transform: uppercase;
  margin-bottom: 14px;
}
.header__title { font-size: 28px; font-weight: 650; margin: 0 0 4px; letter-spacing: -0.01em; }
.header__subtitle { font-size: 15px; color: #C4CCC7; margin: 0 0 24px; }
.header__meta {
  display: flex; flex-wrap: wrap; gap: 28px;
  font-family: var(--mono); font-size: 12px; color: #9FA8A2;
  border-top: 1px solid #2C3B35; padding-top: 16px;
}
.header__meta strong { color: #DDE4E0; font-weight: 600; }
.header__link { color: #9FD6C2; text-decoration: none; font-weight: 600; }
.header__link:hover { text-decoration: underline; }

/* ---- Score hero ---- */
.hero {
  display: flex; align-items: flex-start; gap: 24px;
  background: var(--panel); border: 1px solid var(--hairline);
  border-radius: 4px; padding: 28px; margin: -28px 0 28px;
  box-shadow: 0 1px 2px rgba(23,35,31,0.04);
}
.dial { text-align: center; min-width: 108px; }
.dial__value {
  font-family: var(--mono); font-size: 44px; font-weight: 700; line-height: 1;
}
.dial__max { font-size: 18px; font-weight: 500; color: var(--ink-faint); }
.dial__label {
  margin-top: 8px; font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-faint);
}
.dial--good .dial__value { color: var(--good); }
.dial--mid .dial__value { color: var(--mid); }
.dial--low .dial__value { color: var(--low); }
.dial--unknown .dial__value { color: var(--unknown); }
.dial__rationale { margin: 0; padding-top: 6px; color: var(--ink-soft); font-size: 15px; flex: 1; }
.hero > .dial__rationale { align-self: center; }

/* ---- Panels ---- */
.panel {
  background: var(--panel); border: 1px solid var(--hairline);
  border-radius: 4px; padding: 24px 28px; margin-bottom: 20px;
}
.panel__eyebrow {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 6px;
}
.panel__title { font-size: 19px; margin: 0 0 14px; font-weight: 650; }
.panel__body p { margin: 0 0 12px; color: var(--ink); }
.panel__body p:last-child { margin-bottom: 0; }
.panel__body ul { margin: 0 0 12px; padding-left: 20px; }
.panel__body li { margin-bottom: 6px; }
.panel__body .empty { color: var(--ink-faint); font-style: italic; }

.subsection { margin-bottom: 18px; }
.subsection:last-child { margin-bottom: 0; }
.subsection h3 {
  font-size: 13px; font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--ink-soft); margin: 0 0 8px;
  border-bottom: 1px solid var(--hairline); padding-bottom: 6px;
}
.subsection p, .subsection ul { color: var(--ink); }

/* ---- Diff / round history ---- */
.round {
  border: 1px solid var(--hairline); border-radius: 4px;
  margin-bottom: 10px; background: var(--panel);
}
.round--base { padding: 14px 18px; }
.round__head {
  display: flex; align-items: center; gap: 12px; cursor: pointer;
  padding: 14px 18px; font-weight: 600; font-size: 14.5px;
  list-style: none;
}
.round__head::-webkit-details-marker { display: none; }
.round__head::before { content: "\\25B8"; color: var(--ink-faint); font-size: 12px; }
details[open] > .round__head::before { content: "\\25BE"; }
.round--base .round__head::before { content: ""; }
.round__score {
  font-family: var(--mono); font-size: 12px; padding: 2px 8px;
  border-radius: 3px; margin-left: auto;
}
.round__score--good { color: var(--good); background: var(--good-bg); }
.round__score--mid { color: var(--mid); background: var(--mid-bg); }
.round__score--low { color: var(--low); background: var(--low-bg); }
.round__score--unknown { color: var(--unknown); background: var(--unknown-bg); }
.round__body { padding: 4px 18px 16px; }

pre.diff {
  font-family: var(--mono); font-size: 12.5px; line-height: 1.55;
  background: #0F1714; color: #DDE4E0; border-radius: 4px;
  padding: 12px 14px; margin: 0;
  /* was white-space: pre with overflow-x: auto -- fine for short code
     diffs, unreadable for long text lines (a whole paragraph as one
     "line" renders as one unbroken horizontal string). pre-wrap keeps
     the monospace/whitespace-significant formatting real diffs still
     want while actually wrapping long lines inside the panel. */
  white-space: pre-wrap;
  overflow-wrap: break-word;
}
.diffline { display: block; }
.diffline--add { color: #8FD9B6; }
.diffline--del { color: #F0A594; }
.diffline--hunk { color: #7FB8D6; }
.diffline--hdr { color: #9FA8A2; }
.diffline--ctx { color: #C4CCC7; }

/* ---- Word-level diff (prose sections: summary, cover letter) ---- */
p.worddiff {
  font-size: 14.5px; line-height: 1.6; color: var(--ink);
  background: var(--bg); border-radius: 4px; padding: 12px 14px; margin: 0;
  white-space: pre-wrap; overflow-wrap: break-word;
}
.worddiff__del {
  color: var(--low); background: var(--low-bg); text-decoration: line-through;
  text-decoration-thickness: 1px; border-radius: 2px; padding: 0 1px;
}
.worddiff__ins {
  color: var(--good); background: var(--good-bg); text-decoration: none;
  border-radius: 2px; padding: 0 1px;
}

/* ---- Job description (collapsed by default) ---- */
details.jd summary {
  cursor: pointer; font-family: var(--mono); font-size: 12px;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft);
  padding: 10px 0;
}
details.jd .panel__body { white-space: pre-wrap; font-size: 14px; color: var(--ink-soft); }

.raw-critique summary {
  cursor: pointer; font-family: var(--mono); font-size: 12px;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft);
  padding: 4px 0 12px;
}
.raw-critique pre {
  white-space: pre-wrap; font-family: var(--sans); font-size: 14px;
  color: var(--ink); background: none; margin: 0; padding: 0;
}

.footer {
  color: var(--ink-faint); font-size: 12px; font-family: var(--mono);
  text-align: center; padding-top: 12px;
}

@media (max-width: 640px) {
  .hero { flex-direction: column; align-items: center; text-align: center; }
  .header { padding: 28px 16px 24px; }
  .panel { padding: 18px; }
}
"""


def render_posting_report(
    result: RevisionResult,
    company_name: str,
    job_title: str,
    job_description: str,
    round_diffs: list[RoundDiff] | None = None,
    model_routing: dict[str, str] | None = None,
    generated_at: datetime.datetime | None = None,
    dashboard_url: str | None = None,
) -> str:
    """Renders one posting's full pipeline output as a self-contained
    HTML string.

    result: the output of revision.run_revision_loop() (or a single-
    round RevisionResult built by hand around one generate_draft() +
    critique_draft() call -- nothing here requires more than one round
    to have run; a 1-element `rounds` list just renders with no round
    history section beyond the base round).

    round_diffs: from diff.diff_revision_result(result). Optional --
    pass None (or an empty list, same effect) if you only want the
    final draft/critique/score and don't need the round-by-round diff
    view; the report renders fine without it, just without that panel.

    model_routing: optional {role: "provider/model"} to print in the
    header meta row (e.g. {"writer_selection": "ollama/gemma4:12b-mlx",
    "critic_review": "ollama/gemma4:12b-mlx"}) -- purely informational,
    lets you tell at a glance whether a given report ran against local
    or cloud models, which matters a lot right now given the
    Anthropic-access note carried in the 2026-08-07 handoff.

    generated_at: defaults to now (UTC). Exposed as a param mainly so
    tests/spot-checks can pass a fixed timestamp instead of asserting
    against a moving target.

    dashboard_url: optional link back to this posting's dashboard page
    (e.g. http://localhost:5050/postings/123), rendered as a link in the
    header. None (the default) omits it entirely -- this is the right
    default for cli.py's `report` command, which has no running
    dashboard to link back to; dashboard.py's posting_report() route is
    the one real caller that passes this (2026-08-13 handoff: reports
    had no way back to the dashboard that generated them).
    """
    round_diffs = round_diffs or []
    generated_at = generated_at or datetime.datetime.now(datetime.timezone.utc)
    rid = report_id(company_name, job_title, generated_at)

    final_score = parse_score(result.final_critique)

    meta_bits = [
        f"<span><strong>{len(result.rounds)}</strong> round(s)</span>",
        f"<span>Generated <strong>{_esc(generated_at.strftime('%Y-%m-%d %H:%M UTC'))}</strong></span>",
    ]
    if model_routing:
        routing_str = ", ".join(f"{role}: {model}" for role, model in model_routing.items())
        meta_bits.append(f"<span>{_esc(routing_str)}</span>")
    if dashboard_url:
        meta_bits.append(f'<span><a class="header__link" href="{_esc(dashboard_url)}">&larr; Back to dashboard</a></span>')

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(company_name)} — {_esc(job_title or 'Untitled posting')} — BioHunter Report</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="header">
  <div class="header__inner">
    <div class="header__id">Report {_esc(rid)}</div>
    <h1 class="header__title">{_esc(company_name)}</h1>
    <p class="header__subtitle">{_esc(job_title) or 'Job title not given'}</p>
    <div class="header__meta">{''.join(meta_bits)}</div>
  </div>
</div>
<div class="wrap">

  <div class="hero">
    {_render_score_dial(final_score, 'Final ATS score')}
  </div>

  {_render_draft_panel('01', 'Tailored Summary', _render_prose_block(result.final_draft.tailored_summary))}
  {_render_draft_panel('02', 'Tailored Resume', _render_tailored_bullets(result.final_draft.tailored_bullets))}
  {_render_draft_panel('03', 'Cover Letter', _render_prose_block(result.final_draft.cover_letter))}
  {_render_draft_panel('04', 'Critique', _render_critique(result.final_critique))}

  <details class="raw-critique">
    <summary>Full critique text (raw)</summary>
    <pre>{_esc(result.final_critique)}</pre>
  </details>

  <section class="panel">
    <div class="panel__eyebrow">05</div>
    <h2 class="panel__title">Revision History</h2>
    {_render_round_history(result.rounds, round_diffs)}
  </section>

  <details class="jd">
    <summary>Job description used for this draft</summary>
    <div class="panel__body">{_esc(job_description)}</div>
  </details>

  <div class="footer">BioHunter — generated report, not submitted anywhere. Human review still required before applying.</div>
</div>
</body>
</html>"""
    return body
