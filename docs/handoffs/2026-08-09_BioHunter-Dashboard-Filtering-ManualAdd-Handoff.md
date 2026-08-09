BioHunter — Dashboard, Resume PDF Export, Scout Description Cleanup (2026-08-09)

Project Summary

BioHunter is a self-hosted, local-first AI platform that automates biotech
job searching and application preparation.

Pipeline:

Scout
    ↓
Scorer          <- NOT YET BUILT (see "Two different scores" below — this matters a lot for next session)
    ↓
Writer
    ↓
Critic
    ↓
Human Review

This session built the "dynamic dashboard" ADR-0006 originally deferred
("revisit only once there's a concrete need") — that need arrived: the
project owner wants to browse postings, generate a resume/cover letter for
one by clicking it, review the critique, and export a submittable PDF,
rather than running CLI commands by hand per posting. That's now live and
working. What it exposed once real data hit it (693 real postings, a live
screenshot) is this session's actual handoff: the dashboard has no way to
narrow 693 postings down to the handful worth generating for, and no way
to add a posting Scout didn't find on its own.

⸻

1. What Was Built This Session

All four pieces below are done, wired, and tested — the last three were
built and validated in-sandbox against synthetic data shaped exactly like
real pipeline output (no live Ollama/Qdrant available there), then the
`report` CLI command was separately confirmed against a REAL run (Guardant
Health, Senior Scientist Mass Spec posting, score 6/10, 2 rounds, --debug
log reviewed). The dashboard itself is now confirmed live and running
against real data per the screenshot (693 postings, Amgen populating the
default view).

1a. Static single-posting HTML report — src/biohunter/report.py +
cli.py's `report` subcommand (ADR-0006 decision #3 / ROADMAP's
`biohunter report` item). Renders one posting's Writer/Critic/Revision
output as a self-contained HTML file: score dial, tailored summary/resume/
cover-letter, critique broken into its six headers, round-by-round diff
history in collapsible <details>, job description collapsed by default.
Deliberately single-posting only — a multi-posting index was explicitly
deferred to a later pass, which is most of what THIS handoff is about.

1b. Local dashboard — src/biohunter/dashboard.py (Flask). Calls
run_revision_loop()/diff_revision_result() DIRECTLY (same functions
cli.py's `report` command already calls) rather than shelling out to the
CLI as a subprocess — one pipeline implementation either way, this just
skips the extra process boundary. Single local process, no auth, not
meant to be exposed past localhost. Generation runs in a background
thread (real local-Ollama runs take minutes; the request thread never
blocks on it) — POST /postings/<id>/generate returns a job id immediately,
the browser polls /jobs/<job_id>.json until done. Routes: index (posting
list with score badges), posting detail (JD view/paste, Generate/
Regenerate, links to report + both PDFs), report view, resume.pdf,
cover-letter.pdf.

1c. Draft persistence — src/biohunter/drafts_db.py + a new `drafts` table
in schema.sql. One row per generation RUN (not per posting) — Regenerate
adds a row, never overwrites, so history isn't lost even though only the
latest is surfaced in the UI today. Serializes/deserializes a
RevisionResult to/from JSON; writer.py/critic.py/revision.py themselves
are untouched. `final_score` is denormalized onto the row (Critic's
parsed SCORE for the final round) so the dashboard's posting list can
show a badge without deserializing every draft's JSON on every page load.
GOTCHA hit and fixed: db.py's _split_statements() splits schema.sql
naively on `;` without stripping comments first — a semicolon inside a
-- comment silently breaks schema init. Watch for this in any future
schema.sql edit.

1d. Plain resume/cover-letter PDF export — src/biohunter/resume_pdf.py.
Deliberately a SEPARATE template from the dashboard's dossier styling —
plain black-on-white, single column, no score/diff chrome — the actual
submittable copy. Renders via Playwright's headless Chromium print-to-PDF
(new dependency: `pip install playwright && playwright install chromium`,
one-time browser download). OPEN ITEM, not solved: WriterDraft carries no
candidate name/contact info — the Qdrant catalog only ever produces
resume BODY content — so both render functions take optional
candidate_name/contact_line params and simply omit the header block if
not given, rather than inventing a placeholder. Still needs a real answer
for where that data should live (dashboard settings field, config file,
env var) before a submitted PDF looks complete.

1e. Scout description HTML cleanup — src/biohunter/scout/detector.py.
Root cause: greenhouse.py's own comment says its `content` field is
"HTML; caller may strip tags" — nobody ever did, so postings.description
was storing raw HTML, which the new dashboard then displayed as escaped
tag soup and fed verbatim into every Writer/Critic prompt as job_description.
Fixed with a new _clean_description() applied centrally in
_upsert_postings() (covers every ATS adapter uniformly, not just
Greenhouse, including any adapter added later). FIRST VERSION HAD A REAL
BUG: a naive get_text(separator="\n\n") inserts that separator between
EVERY child node, including inline tags like <strong>/<em>, fragmenting
ordinary sentences into fake paragraphs. Fixed version only breaks lines
at block-level tags (p/div/li/headings/tr); <li> items get a "- " prefix
so bullet lists survive as bullet lists. Also fixed: _upsert_postings()
now refreshes description on every re-sighting (previously frozen at
whatever it was on first insert, forever) via COALESCE so a fetch
returning nothing never blanks out text that was already there. Flagged,
not solved: a manual dashboard-side edit to description (e.g. pasting a
JD for a fallback-scraped posting with no ATS description) CAN be
overwritten by a later Scout run if the source starts returning real
content for it — no "manually edited, leave alone" flag exists on the
row.

⸻

2. Current State (per the 2026-08-09 5:16pm screenshot)

Dashboard is live and rendering real data: 693 postings, mostly Amgen at
the top of the default (alphabetical-by-company) sort. Every card shows
"not generated" — none of the 693 have a draft yet, which is expected;
nothing has been generated against real data yet, only the earlier
synthetic-data smoke tests.

The screenshot itself makes the next problem obvious without needing to
be told: the visible postings are Kitchener/Waterloo (Canada), Reading
PA, Los Angeles, Rhode Island, Algiers, Guangzhou, "United States -
Remote" — i.e. exactly the kind of noise a real 693-posting company-wide
scrape produces, with no way on-screen to narrow it to "Bay Area, biotech-
analytical-chemistry-relevant, posted recently." Generating is a multi-
minute local-LLM operation per posting — nobody is going to click
Generate 693 times to find the ones worth drafting for. Filtering isn't a
nice-to-have polish item here, it's the thing standing between "the
dashboard works" and "the dashboard is usable."

The project owner has also flagged a second, separate gap: no way to
manually add a posting Scout didn't surface on its own — concretely, they
keep re-testing against the same Guardant Health, Senior Scientist Mass
Spec posting by hand (--job-description-file on the CLI) rather than
having it live in the dashboard like everything else.

⸻

3. NEXT SESSION: Two Things To Build

3a. Postings index filtering (the higher-leverage, more urgent one)

Requested filter dimensions, verbatim from the project owner: keyword,
location (Bay Area specifically called out), company, date of posting,
and "ATS score or possibly job likeliness based on my collection of
resumes."

CHECK BEFORE BUILDING, likely saves real time: cli.py's own AST skeleton
(generated earlier this project) lists module-level constants
DEFAULT_EXCLUDE_KEYWORDS and DEFAULT_BAY_AREA_LOCATIONS under cli.py —
meaning cmd_list_postings may ALREADY implement keyword and Bay-Area
location filtering for the CLI's `list-postings` command. If so, the
dashboard's filtering should reuse that exact logic (extract it to a
shared helper both cli.py and dashboard.py import, or import directly
from cli.py) rather than reimplementing location-string matching from
scratch — "US - California - Los Angeles" / "United States - Remote" /
"Canada - Ontario" are free-text strings, not a structured field, so
whatever matching approach already exists and is tuned is worth reusing
rather than duplicating a second, possibly-inconsistent version of the
same heuristic. Read cli.py's full cmd_list_postings before writing any
new filter code.

Straightforward pieces (existing schema already supports these, this is
just query + UI work):
  - Company: companies.name via the existing JOIN, dropdown or
    multi-select.
  - Date of posting: postings.first_seen_at (or last_seen_at) already
    exists — date-range inputs.
  - Keyword: postings.title / postings.description — SQL LIKE is
    probably sufficient at this scale (693 rows), no need for a search
    index.
  - Location / Bay Area: see the cli.py reuse note above before building
    fresh.

NOT straightforward — needs a real design conversation before building,
don't guess: "ATS score or job likeliness based on my collection of
resumes." Two DIFFERENT scores exist in this codebase and are easy to
conflate:
  - postings.score / postings.score_rationale — a job-FIT score (fit to
    the candidate, location, seniority, visa, salary, preferences),
    produced by the Job-fit Scorer agent. Per ROADMAP, Scorer is NOT YET
    BUILT. This column exists in the schema but nothing populates it
    today.
  - drafts.final_score — Critic's 1-10 resume-QUALITY score, parsed from
    critic.py's critique text, and it only exists for a posting AFTER a
    draft has already been generated for it.
  Filtering by drafts.final_score only helps AFTER you've already
  generated — it can't help triage which of 693 postings to generate for
  in the first place, which is what "job likeliness based on my resume
  collection" actually sounds like it's asking for. That's really a
  request for the Scorer agent (ROADMAP Phase 2, not yet built) — a
  real, separate, larger piece of work (semantic matching against the
  same Qdrant resume_content collection Writer already uses, most
  likely), not a dashboard filter. Recommend surfacing this distinction
  to the project owner explicitly and deciding on purpose whether Scorer
  is in scope for next session or a session after — don't quietly build
  a shallow proxy (e.g. keyword-matching title against resume keywords)
  that LOOKS like what was asked for but isn't the real thing, per this
  project's own stated working style of naming a real scope decision
  instead of letting it happen by omission.

Also worth building alongside filtering, not requested explicitly but a
direct consequence of the 693-posting screenshot: pagination or a result-
count cap on the index route. Rendering 693 cards server-side in one
unpaginated page already works today only because nobody's scrolled to
the bottom yet.

3b. Manual posting entry

A form (new dashboard route, e.g. POST /postings/manual) to add a
posting Scout didn't find: company name, title, url, location, job
description pasted directly. Needs a "find or create company by name"
step — schema.sql's postings.company_id is NOT NULL REFERENCES
companies(id), so a manually-added posting still needs a company row.
detector.py's _get_or_create_company_id() is close to this shape already
but takes a full CompanyConfig (from companies.yaml) — a manual-add path
probably wants a lighter-weight version that only needs a name, not a
full registry entry (ats_type/ats_slug/css_selector can stay NULL, same
as any company added by hand outside the registry). Once inserted, a
manually-added posting behaves exactly like any Scout-found one — same
Generate button, same report, same PDFs — no special-casing needed
downstream.

This directly solves the Guardant Health re-testing annoyance: paste it
in once, then use Generate/Regenerate from the dashboard like everything
else, instead of re-typing --job-description-file on the CLI each time.

⸻

Recommended Files to Upload (next session)

Core (all touched or directly relevant this session)
src/biohunter/dashboard.py       (this session, new)
src/biohunter/drafts_db.py       (this session, new)
src/biohunter/resume_pdf.py      (this session, new)
src/biohunter/report.py          (prior session, unchanged but dashboard imports it)
src/biohunter/scout/detector.py  (this session, HTML cleanup fix)
schema.sql                        (this session, added `drafts` table)
src/biohunter/cli.py              (NEEDED — has the DEFAULT_BAY_AREA_LOCATIONS /
                                    DEFAULT_EXCLUDE_KEYWORDS constants and
                                    cmd_list_postings; read before building
                                    any new filter logic)
src/biohunter/config.py           (NEEDED — CompanyConfig/load_companies,
                                    for the manual-add "find or create
                                    company" path)
src/biohunter/db.py               (unchanged, but every new query goes
                                    through get_connection()/init_schema())

Reference
FILE_TREE.txt                     (updated this session's file additions
                                    are NOT yet reflected — regenerate
                                    before next session if convenient)

Latest handoffs
2026-08-07_BioHunter-Diff-Score-BulletFix-Handoff.md  (prior session)
this file

⸻

Working Style

Continue the mentoring style used throughout this project:

* Explain rationale before coding.
* Check for existing logic before building new logic — this session's
  own note above (cli.py's DEFAULT_BAY_AREA_LOCATIONS) is exactly this
  principle: don't reimplement Bay Area matching if cmd_list_postings
  already does it.
* Avoid unnecessary abstraction.
* Favor incremental, testable milestones — this session's every new
  module (report.py, dashboard.py, drafts_db.py, resume_pdf.py,
  detector.py's fix) was validated against synthetic or real data before
  being called done; the bug in the first HTML-cleaning attempt (inline
  tags fragmenting sentences) was only caught because it was tested
  against a realistic payload instead of eyeballed.
* If a proposed change would intentionally diverge from prior behavior,
  say so explicitly rather than letting it look like a small addition.
  This session: _upsert_postings() now refreshing description on every
  re-sighting (previously frozen at first insert) was called out as a
  real behavior change, not folded in silently.
* No auto-submit / no auto-send — human approval remains the final step
  before application submission. Nothing this session changes this; the
  dashboard's PDF export is explicitly a "download to manually submit"
  feature, not a submit button.
* Don't build a shallow version of something bigger just because it's
  faster — see the Scorer-vs-Critic-score distinction above. Name the
  real scope, let the project owner decide, don't decide it by omission.
