"""
Plain, ATS-conventional resume + cover letter PDF export -- the copy
you'd actually submit for a job, as opposed to report.py's dashboard-
styled dossier (dark header, score dial, diffs), which is for
reviewing the pipeline's own output, not for handing to an employer.

Deliberately a SEPARATE, minimal template: no color accents, no score
readout, single column, plain black-on-white -- closer to what a
traditional Word-exported resume looks like. Reuses report.py's two
markdown-shape helpers (_split_headed_sections, _render_prose_block)
rather than re-implementing the same small "## Heading" / "- item"
parser twice; this module owns layout/styling only, not text parsing.

PDF rendering uses Playwright's headless Chromium (print-to-PDF), not
a pure-Python PDF library -- avoids a WeasyPrint-style system-library
dependency (Pango/Cairo) that's a known pain on macOS without Homebrew.
New dependency: `pip install playwright && playwright install chromium`
(one-time browser download; see the module-level NOTE below).

OPEN ITEM, not solved here: WriterDraft carries no candidate
name/contact info (email, phone, LinkedIn) -- that was never part of
the Qdrant catalog or the selection branches, all of which only ever
produce resume BODY content. render_resume_html()/render_cover_letter_html()
accept optional candidate_name/contact_line params and simply omit the
header block if they're not given, rather than inventing placeholder
values. Wire these from wherever you want that data to live (a
dashboard settings page, an env var, a config file) -- not decided
here.
"""
from __future__ import annotations

import html

from .report import _render_prose_block, _split_headed_sections
from .writer import WriterDraft

_esc = html.escape

# NOTE: first call to html_to_pdf_bytes() on a fresh machine needs
# Chromium downloaded once via `playwright install chromium`. If that
# hasn't been run, Playwright raises a clear "Executable doesn't
# exist" error naming the exact command to run -- not swallowed here,
# since silently retrying or falling back would hide a one-time setup
# step behind a confusing failure on first PDF download.

_RESUME_STYLE = """
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: Georgia, "Times New Roman", serif;
    color: #1A1A1A; font-size: 11pt; line-height: 1.42;
  }
  .page { padding: 0.15in 0; }
  .name { font-size: 20pt; font-weight: 700; margin: 0 0 2px; letter-spacing: 0.01em; }
  .contact { font-size: 9.5pt; color: #444; margin: 0 0 14px; }
  .summary { margin: 0 0 16px; }
  h2 {
    font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.06em; color: #1A1A1A;
    border-bottom: 1px solid #1A1A1A; padding-bottom: 2px; margin: 16px 0 8px;
  }
  h2:first-of-type { margin-top: 0; }
  p { margin: 0 0 8px; }
  ul { margin: 0 0 8px; padding-left: 18px; }
  li { margin-bottom: 4px; }
  .empty { display: none; }
"""

_COVER_LETTER_STYLE = """
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: Georgia, "Times New Roman", serif;
    color: #1A1A1A; font-size: 11.5pt; line-height: 1.55;
  }
  .page { padding: 0.15in 0; }
  .letterhead-name { font-size: 15pt; font-weight: 700; margin: 0 0 2px; }
  .letterhead-contact { font-size: 9.5pt; color: #444; margin: 0 0 28px; }
  p { margin: 0 0 12px; }
"""


def render_resume_html(
    draft: WriterDraft, candidate_name: str = "", contact_line: str = ""
) -> str:
    """tailored_bullets already carries its own '## Heading' structure
    (assemble_draft() in selection.py) -- rendered here as h2 sections
    rather than re-labelled, so heading text stays exactly what the
    catalog/model produced (Career History, Professional Experience,
    Key Skills, Education, Selected Publications, Patents, Honors and
    Special Awards)."""
    header = ""
    if candidate_name:
        header += f'<div class="name">{_esc(candidate_name)}</div>'
    if contact_line:
        header += f'<div class="contact">{_esc(contact_line)}</div>'

    sections = []
    for heading, body in _split_headed_sections(draft.tailored_bullets):
        body_html = _render_prose_block(body)
        if '<p class="empty">' in body_html:
            # An empty catalog section (e.g. no patents) -- omit the
            # heading entirely rather than printing "Patents" over
            # nothing, since this copy goes to an employer, not a
            # debugging view.
            continue
        label = heading if heading else "Summary"
        sections.append(f"<h2>{_esc(label)}</h2>{body_html}")

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{_esc(draft.company_name)} — Resume</title>
<style>{_RESUME_STYLE}</style></head>
<body><div class="page">
{header}
<h2>Summary</h2>
<div class="summary">{_render_prose_block(draft.tailored_summary)}</div>
{''.join(sections)}
</div></body></html>"""


def render_cover_letter_html(
    draft: WriterDraft, candidate_name: str = "", contact_line: str = ""
) -> str:
    header = ""
    if candidate_name:
        header += f'<div class="letterhead-name">{_esc(candidate_name)}</div>'
    if contact_line:
        header += f'<div class="letterhead-contact">{_esc(contact_line)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{_esc(draft.company_name)} — Cover Letter</title>
<style>{_COVER_LETTER_STYLE}</style></head>
<body><div class="page">
{header}
{_render_prose_block(draft.cover_letter)}
</div></body></html>"""


def html_to_pdf_bytes(html_str: str) -> bytes:
    """Renders one HTML string to PDF bytes via headless Chromium.
    Launches a fresh browser instance per call rather than keeping one
    warm across requests -- simplest thing that works for a single-
    user local tool downloading a PDF occasionally; the ~1-2s Chromium
    startup cost isn't worth a persistent-browser-process abstraction
    at this usage rate. Revisit only if PDF downloads become frequent
    enough for that cost to actually matter.
    """
    from playwright.sync_api import sync_playwright  # lazy import: only PDF export needs Playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_str, wait_until="load")
            return page.pdf(
                format="Letter",
                margin={"top": "0.6in", "bottom": "0.6in", "left": "0.75in", "right": "0.75in"},
                print_background=True,
            )
        finally:
            browser.close()
