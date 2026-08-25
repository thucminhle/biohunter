# BioHunter — Captain Subsystem Closed; Writer Subsystem Steps 1-3 Built (Editor, Preview/Export, Regenerate-Archiving)

**Session date:** 2026-08-25. Builds directly on
`2026-08-24_1_BioHunter-CostCalculatorComplete-Handoff.md` (previous
session, same date range) — that handoff flagged Captain roadmap item
#4 (Scout+dead-link-check combined job) as "user-reported done, NOT
verified in-thread." This session closes that loop and moves on to the
Writer/export subsystem (`docs/ROADMAP.md`'s "4. Writer / export").

---

## 1. Captain subsystem — CLOSED (all 5 items), `docs/ROADMAP.md` updated

The prior handoff's unverified claim was resolved by direct code
inspection of the user's actual current `dashboard.py` (not taken on
faith): `_run_scout_and_check_job()`, route `POST /scout-and-check/run`,
job kind `"scout_and_check"` are all real and fully wired into
cancellation, `job_status_json`, `jobs_index`, and `dead_links_results()`.
Mechanism: **one job_id, two sequential phases** (`job["phase"]` flips
from `"scout"` to `"dead_link_check"` partway through), not two chained
jobs. User then independently confirmed it live via their own
click-through test.

All 5 Captain checkboxes in `docs/ROADMAP.md` are now checked off:
persisted job queue, multi-select batch generation, unified
progress-bar contract, combined scout+check job, permanent DB-backed
`/jobs` history page. **This file was updated and handed back this
session** — if the next AI session is reading a copy of `ROADMAP.md`
older than this handoff, re-pull it.

## 2. Writer subsystem (dashboard subsystem #4) — steps 1-3 of 6 built

Per `docs/ROADMAP.md`'s own item numbering, "Writer subsystem" here
means the **in-dashboard editor / DOCX export / proofreader / version
history** section — NOT `writer.py`/`critic.py`/`revision.py` (that
pipeline is unchanged and untouched this session). Build order chosen
and confirmed with the user: editor (foundational) → preview/export →
regenerate-archiving → version history → local-LLM proofreader → DOCX
export. Steps 1-3 below are done; steps 4-6 are not started.

### Step 1 — In-dashboard editor: DONE, confirmed live
- **New table `final_edit`** (schema.sql) — one row per posting_id,
  always upserted in place, holds the CURRENT hand edit only (never a
  history). Deliberately separate from `drafts` so `diff.py`'s
  round-to-round comparison across AI drafts is never affected by hand
  edits.
- **`drafts_db.py`**: `get_final_edit()`, `save_final_edit()`,
  `clear_final_edit()`.
- **`dashboard.py`**: new editor panel on `posting_detail()` (only
  shown once a draft exists) — seeded from the active edit if one
  exists, else from the latest AI draft's own fields. Two new routes:
  `POST /postings/<id>/edit` (`save_edit`), `POST
  /postings/<id>/edit/reset` (`reset_edit`).
- **Confirmed live by user**: save persists after a cold reload, reset
  reverts correctly.
- **CSS pass done same session** (user's only feedback: didn't like
  the initial look) — `.editor-panel`/`.editor-field`/`.editor-box`/
  `.edited-badge` rules added to `_DASHBOARD_STYLE`: custom disclosure
  triangle, panel bg/border matching existing `--panel`/`--hairline`
  vars, per-field labels/spacing, shorter per-field textarea heights
  than the old shared `.jd-box` (240px → 100px summary/cover,
  160px bullets). User confirmed this looks good. Note: this was a
  panel-level CSS fix, NOT the Workspace subsystem (roadmap item #3,
  untouched) — Workspace will add page-level layouts/palettes on top
  of this later, it doesn't replace this panel's own styling.

### Step 2 — Preview + PDF export reading from final_edit: BUILT, NOT confirmed live
- **`_display_draft(draft, edit)`** helper in `dashboard.py` —
  `dataclasses.replace()` merges the edit's 3 fields
  (tailored_summary/tailored_bullets/cover_letter) onto a copy of the
  AI draft's `WriterDraft`, leaving `company_name`/`job_title`/
  `cover_letter_blocks` untouched.
- **Two new HTML preview routes**: `posting_resume_preview` at
  `/postings/<id>/resume/preview`, `posting_cover_letter_preview` at
  `/postings/<id>/cover-letter/preview` — reuse
  `render_resume_html`/`render_cover_letter_html` unchanged, just a
  new content source, per the roadmap's own wording.
- **Existing PDF routes** (`posting_resume_pdf`,
  `posting_cover_letter_pdf`) now also call `_display_draft()`, so
  preview and PDF are guaranteed to match.
- **Two new "Preview ..." links** added to `posting_detail()`'s action
  row, next to the existing Download PDF links.
- **NOT explicitly click-tested this session** — the user moved
  straight to step 3 without confirming. Worth a quick pass next
  session before assuming it's flawless: edit → Preview resume (should
  show the edit) → Download resume PDF (should also show the edit,
  since it's a genuinely separate code path through
  `html_to_pdf_bytes()`/headless Chromium) → same for cover letter →
  Reset to AI draft → confirm both revert.

### Step 3 — Regenerate-while-editing archiving: DONE, confirmed live (single + batch)
- **New table `archived_edit`** (schema.sql) — one row PER ARCHIVE
  EVENT (unlike `final_edit`'s single-current-row-per-posting), so
  repeated edit/regenerate cycles on the same posting accumulate
  multiple archived rows, each a real moment in that posting's
  history.
- **`drafts_db.archive_final_edit(conn, posting_id) -> bool`** — if an
  active edit exists, copies it into `archived_edit` (preserving its
  original `edited_at`) and clears `final_edit`. Returns `False`
  (no-op) if there was nothing to archive — the common case.
- **Wired into BOTH places that can regenerate a posting**: the
  single-posting `generate()` route, and `_run_batch_generation()`'s
  per-posting loop (batch generation can regenerate a posting that
  already has a draft — and possibly an active edit — same as clicking
  Regenerate individually; `batch_generate_confirm()`'s own docstring
  already documents this "adds a new draft row, same as Regenerate"
  behavior).
- **Confirmed live by user**: both the single-posting test and the
  batch-generation test passed.

## 3. Bug hit and fixed this session (recurrence of a known bug class)

A semicolon inside `archived_edit`'s own schema.sql comment
(`"...was last saved); archived_at is..."`) broke `db.py`'s naive
`.split(";")` statement splitter — **the exact same bug class** as the
2026-08-23 `run_log` incident already documented in a prior handoff,
which this session's own comment-writing should have avoided and
didn't. Symptom this time was `ValueError: not an error` (vs.
`ValueError: incomplete input` on 2026-08-23 — different message from
`libsql_experimental`, same root cause).

**Root-caused, not guessed**: a temporary diagnostic was added to
`db.py`'s `init_schema()` (wrapping each statement's `conn.execute()`
in try/except to print the failing statement's index and full text
before re-raising), which immediately identified statement 12 of 20 as
a pure comment fragment with no SQL in it — proof the split had
happened mid-comment. Fixed (semicolon replaced with an em-dash
aside), diagnostic wrapper removed, `db.py` is back to its original
form.

**Real lesson, stated plainly**: verifying "does the full script
execute cleanly against Python's `sqlite3` module" is **NOT
sufficient** to catch this bug class — `sqlite3` silently tolerates a
stray comment-only fragment as a harmless no-op, while
`libsql_experimental` (this project's real runtime) does not. That
false-confidence check was actually run this session and still missed
the bug. **Before handing back any schema.sql edit, explicitly grep
every comment line for a literal `;`** — that's the only check that
actually simulates the naive splitter's real failure mode. Consider
making this a standing pre-flight step for every future schema.sql
touch, not just a lesson to remember.

## 4. Writer subsystem — what's left (steps 4-6, not started)

- **Step 4 — Version history panel.** Needs a new
  `list_drafts_for_posting(conn, posting_id)` in `drafts_db.py` (today
  only `get_latest_draft()`/`get_draft_by_id()` exist) plus a similar
  lister for `archived_edit` rows, flattened into one chronological
  `<details>`/`<summary>` list per the roadmap's wording. Scope
  decision already made in the roadmap: generation history only, NOT
  rejected proofreader suggestions.
- **Step 5 — Local-LLM proofreader.** Per-section, not
  whole-document. Depends on step 4's word-level diff view (reused,
  not rebuilt) for the accept/discard UI.
- **Step 6 — `resume_docx.py` + candidate signature image.**
  Genuinely independent of steps 1-5 — could be picked up any time,
  including out of order, without blocking on version history or the
  proofreader. New dependency: `pip install python-docx`.

## 5. Standing open items, carried forward unchanged from prior handoffs

None of this was touched this session — still open per all available
evidence:
- Single-posting generate's cancel mechanism — still only "appears to
  work per user report," not fully traced through `writer.py`.
- Scribe Therapeutics Greenhouse-board 404 / Lever (Mammoth) dead-link
  detection — both still open.
- "Example Biotech Inc" stale test entry still in the DB.
- `is_posted: false` filtering — still open.
- `cli.py`'s lack of PDF/stability wiring — still open.
- MVP verification punch-list (candidate name in PDF, strict/loose
  stability, inline bold rendering, word-diff view, dashboard-link
  footer, browser notifications) — still no evidence of user
  click-through.
- Workspace subsystem (roadmap item #3: shared data layer,
  `dashboard_settings` palettes, topbar nav, 3 layout renderers) —
  entirely untouched, explicitly deferred until after Writer subsystem
  per user's stated priority.

## 6. Working style — unchanged

Vibe-coded: files uploaded to chat, edited, downloaded, dropped into
the local repo by hand (no Claude Code/IDE integration). **Every code
change handed back as a complete file this session, including
schema.sql and drafts_db.py** — a step-1-session mistake (giving those
two as copy-paste instructions instead of full files) caused this
session's own working copy to silently drift from the user's real
repo state; corrected from step 3 onward and should stay corrected
going forward. User wants mentorship, not just finished code — walk
through development and testing step by step, explain rationale before
coding, heavier implementation can be written directly but should be
explained.

## 7. How to pick this up

1. Confirm current `schema.sql`/`drafts_db.py`/`dashboard.py`/`db.py`
   match this session's output — `grep -n archived_edit
   src/biohunter/dashboard.py` and `config/schema.sql` (well,
   `schema.sql` at repo root — see FILE_TREE.txt) should both find
   real hits; `python -m biohunter.db` should apply cleanly with no
   traceback.
2. **First priority**: click-through test step 2 (Preview + PDF export
   reading from final_edit) — see Section 2's own test steps. This is
   the one piece of this session's work that was built but never
   confirmed live.
3. Then move to step 4 (version history panel) per Section 4, unless
   the user directs otherwise.
4. Before handing back ANY schema.sql edit, explicitly grep every
   comment line for `;` first — see Section 3. Don't rely on "does the
   full script execute in sqlite3" alone; it will not catch this bug
   class.

---
*(End of handoff — paste everything above this line into a new chat.)*
