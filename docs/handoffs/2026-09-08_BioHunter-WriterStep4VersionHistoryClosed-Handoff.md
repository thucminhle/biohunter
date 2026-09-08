# BioHunter handoff — Writer subsystem step 4 (version history) closed

**Read this file first**, per this project's own norm, before touching
`dashboard.py` or any related file. Then pull whatever current files you
need directly from GitHub (see "Access" below) rather than asking the
user to upload them.

## Access

- Repo: `thucminhle/biohunter`, default branch `main`. GitHub read/write
  via Composio, connected to the user's account (`thucminhle`).
- **Write workflow: commit to a feature branch and open a PR for the
  user to review and merge themselves. Never commit straight to `main`.**
  This applies to code AND docs (this handoff doc itself was written
  this way).
- Real file layout is under `src/biohunter/` (`dashboard.py`, `db.py`,
  `drafts_db.py`, `writer.py`, `resume_pdf.py`, etc.), not repo root.
  `schema.sql` and `docs/` are at repo root.

## Hard guardrails (carried through the whole project)

- **No auto-submit / no auto-send, anywhere.** Filler and Networker
  (not yet built) must always stop at a human-approval gate before
  anything goes out.
- **schema.sql pre-flight check, mandatory before touching schema.sql
  specifically:** `db.py`'s `init_schema()` does a naive
  `.split(';')` to run statements. A semicolon anywhere inside a `--`
  comment breaks it -- this has bitten the project 3 times
  (2026-08-23, 2026-08-24, and caught pre-emptively 2026-09-07).
  Testing "does it execute in sqlite3" does NOT catch this (stdlib
  sqlite3 tolerates a stray comment-only fragment as a no-op;
  `libsql_experimental`, what this project actually runs against,
  does not). Before handing back any schema.sql edit, explicitly grep
  every comment line for a stray `;`, or simulate the naive
  `.split(';')` and check for comment-only fragments -- don't just
  syntax-check.

## Working style

- Mentorship, not just finished code: walk through development and
  testing step by step.
- Low-level/teachable code: write it out and have the user type/apply
  it themselves, with an exact anchor line (never a vague "add this
  near X" -- a vague anchor once broke a whole dashboard app).
- Heavier implementation: fine for Claude to write directly, but
  explain what it does.
- Click-test live before moving to the next step, even when a code
  review says the logic is correct -- "reads correctly" isn't the
  same as "renders correctly," and this project treats live
  confirmation as the actual bar, not a formality.

## Status: Captain -- fully closed

All 5 items (persisted job queue, multi-select batch generation,
unified progress-bar contract, combined scout+check job, permanent
job-history page) confirmed done via code + live click-through.

## Status: Writer subsystem -- 4 of 6 steps done, confirmed live

Build order: 1) in-dashboard editor, 2) preview + PDF export reading
from the edit, 3) regenerate-while-editing archiving, 4) version
history panel, 5) DOCX export, 6) local-LLM proofreader.

- [x] Step 1 -- in-dashboard editor (`final_edit` table +
      get/save/clear in `drafts_db.py`, editor panel + 2 routes in
      `dashboard.py`). Confirmed live 2026-08-24.
- [x] Step 2 -- Preview + PDF export both read from `final_edit` via
      `_display_draft()`. Code-reviewed field-by-field and confirmed
      live via click-test 2026-09-07.
- [x] Step 3 -- regenerate-while-editing archiving (`archived_edit`
      table, `archive_final_edit()`). Confirmed live 2026-08-24 (single
      + batch generation, both with an active edit).
- [x] Step 4 -- version history panel. `list_drafts_for_posting()` /
      `list_archived_edits_for_posting()` (`drafts_db.py`) +
      `_history_panel_html()` (`dashboard.py`), merges both tables by
      timestamp into one descending `<details>` list. Built as
      PR #1 (`writer-step4-version-history`), merged into `main`
      2026-09-08, confirmed live by the user (version history visible
      on a real posting with results). `ROADMAP.md`'s Writer/export
      section checkboxes updated in the same PR to match.

## Next up: step 5 (DOCX export) and step 6 (local-LLM proofreader)

Order between these two is NOT yet fixed -- ask the user which they
want first before starting either.

**Step 5 -- DOCX export**, per `ROADMAP.md`'s existing spec:
- `resume_docx.py`, mirroring `resume_pdf.py`'s structure -- reuse
  `report.py`'s shared markdown-parsing helpers
  (`_split_headed_sections`, `_render_prose_block`), swap the
  rendering backend from HTML+Playwright to `python-docx`. New
  dependency: `pip install python-docx`.
- Two new routes, `posting_resume_docx` / `posting_cover_letter_docx`,
  mirroring the existing PDF routes -- almost certainly should also
  read from `_display_draft()` / `final_edit`, same as the PDF routes
  do, for consistency (not explicitly re-confirmed this session, but
  the whole point of `_display_draft()` existing is to be the one
  place every export format reads from).
- Candidate signature image: new `candidate_settings.signature_path`
  field, uploaded via Settings, embedded in both PDF and DOCX cover
  letters between "Sincerely," and the typed name. Not yet scoped in
  detail -- confirm with the user whether this ships alongside DOCX
  export or separately.
- **`AST_OUTLINE.md` was never pulled or read in the 2026-09-07/08
  session** -- worth reading before starting DOCX export in case it
  documents resume-structure assumptions `resume_docx.py` needs to
  match.

**Step 6 -- local-LLM proofreader**, per `ROADMAP.md`'s existing spec:
- Per-section (not whole-document) calls to a local Ollama model,
  narrow instruction (smooth grammar/phrasing, don't add/remove
  substance).
- Never applies silently -- shows a diff (reuse the word-level diff
  view already built for Revision History), user accepts/discards per
  suggestion. Same propose-then-approve pattern as Filler/the
  ATS-adapter wizard.
- Scope note already decided: the version history panel (step 4)
  deliberately does NOT show rejected proofreader suggestions --
  keep that boundary when this is built.

## Loose end, not blocking

`ROADMAP.md`'s Writer/export section still lists the candidate
signature image as unscoped detail (see above) -- worth a quick
confirm-with-user pass before writing any code for it, rather than
guessing the field name/UI.
