# BioHunter Handoff -- Workspace Subsystem (Foundation), 2026-09-13

## Where this picks up

Previous handoff: `docs/handoffs/2026-09-11_BioHunter-WriterStep6HumanizerClosed-Handoff.md`.
Step 5 (DOCX export) is still open but was explicitly deferred this
session in favor of the Workspace subsystem (roadmap section
"3. Workspace (presentation layer)") -- the user's actual goal was
fixing the dashboard's felt experience ("boring" / "hard to navigate
back and forth between postings"), not mechanically checking roadmap
boxes. That framing shaped every decision below.

Branch: `workspace/subsystem-foundation` (off `main`, currently at
commit `7a94058`). **Not yet opened as a PR.** Per the "don't strand
commits with a mid-phase merge" lesson, this stays a feature branch
until the two remaining housekeeping items below are done.

## What shipped

All five build steps from the agreed plan are done and click-tested
live against real data:

1. **`dashboard_settings` table** (schema.sql) -- singleton row
   (`layout_mode`, `palette`, `updated_at`), same CHECK/upsert shape as
   `candidate_settings`. `palette` is reserved but only ever holds
   `"default"` -- see "Explicitly deferred" below.
2. **`dashboard_settings.py`** -- get/save, mirrors `settings_db.py`.
3. **`_filtered_postings()` sort param** -- `company` (default),
   `score_desc` (SQL-level, NULLs last), `quality_desc` (Python-level
   sort against `drafts_by_posting`, since Critic's final_score is a
   join, not a postings column; undrafted postings sort last).
   Corrected a stale roadmap checkbox along the way: the `has_draft`
   filter it also listed was already shipped back on 2026-08-23.
4. **Visual refresh + topbar nav** -- `.topbar` rebuilt as a real flex
   nav (Postings / Jobs / Token usage / Settings, accent-green hover
   underline) replacing the old floated-link stack; `.card` got subtle
   shadow/hover-lift and tighter spacing. Same palette, no new colors.
5. **Master-detail layout (Layout 1 of 3, built first per the
   roadmap's explicit build-order warning)** -- `index()` gained a
   `?selected=<id>` branch: compact left-column list (reusing the same
   filtered/sorted/paginated data, not a second query) + right-column
   detail, with prev/next walking the FULL filtered set (not just the
   current page). Selection is plain full-reload navigation via the
   URL param (user's explicit choice over an AJAX partial-swap).
   `_posting_detail_body(conn, posting_id)` was extracted out of
   `posting_detail()` so both the standalone page and the split view
   render identical detail content from one implementation. Grid
   cards' "View result"/"Generate" links now open the split view by
   default (changed after the user pointed out the split view was
   otherwise undiscoverable, which defeated the point of building it);
   `/postings/<id>` still works identically for direct links.

## Explicitly deferred (flagged to the user, not oversights)

- **The roadmap's 10-palette system (5 light/5 dark)**. `report.py`'s
  CSS vars are hardcoded once in a single `:root` block, not built to
  be runtime-switchable -- making them so, then designing/QA'ing 10
  palettes, is real design work disconnected from the navigation
  complaint that was the actual goal. `dashboard_settings.palette`
  exists so this doesn't need a second migration later, but no palette
  work beyond the single default has been done.
- **Layouts 2 and 3** (kanban / timeline per the roadmap) -- not
  started. Per the roadmap's own build-order warning, Layout 1 needed
  to ship and prove out first.
- **The export report's ("View full report") two-click path back.**
  `posting_report()` returns a bare `Response`, deliberately with no
  topbar -- it's meant to be a self-contained, exportable document, not
  a page browsed inside the dashboard. It DOES already render a
  "<- Back to dashboard" link (via the `dashboard_url` param), but that
  link returns to the standalone `/postings/<id>` page, not the split
  view -- so getting back to Workspace from a report is report -> back
  to dashboard -> Postings (topbar), not one click. User was told about
  this and chose to leave it for now; worth revisiting if it proves
  annoying in daily use.

## Process notes / lessons from this session

- **Gave the user a wrong exact anchor line once** (real import line
  was `from . import drafts_db, settings_db` combined, not
  `from . import drafts_db` alone) -- exactly the vague/wrong-anchor
  failure the user's own guardrail warns about. Caused a chain of
  confusion (a local commit silently never completing, likely aborted
  by the pre-commit doc-regen hook) that took several turns to
  untangle. **Lesson: verify an anchor line actually exists verbatim in
  the current file before handing it to the user, don't reconstruct it
  from memory of having written the file.**
- **Committed a dashboard.py edit via the GitHub API referencing
  `dashboard_settings.py` before confirming that file existed on the
  remote branch.** It didn't yet (see above) -- briefly left the branch
  in a broken state until caught and fixed. **Lesson: before committing
  an edit that references another file/module, verify that file is
  actually present on the target branch, not just assume a
  described-as-done step landed.**
- **A Composio sandbox reset mid-edit lost an in-progress multi-step
  script.** No committed damage (the script hadn't reached its `write`
  call yet), but redone from scratch in one consolidated pass with
  `ast.parse()` verification at every intermediate step and immediate
  commit right after the final verified edit, specifically to shrink
  the window where a reset could lose work again.
- **Hit an f-string quote-nesting bug**: `f'{url_for('index')}...'`
  (same quote character nested inside itself) only parses on Python
  3.12+ (PEP 701) and doesn't match this file's own convention
  (double-quote the `url_for` argument inside a single-quoted
  f-string). Caught and fixed before committing by grepping the
  generated code, not just trusting `ast.parse()` -- a green parse does
  not mean the code matches house style or is safe across Python
  versions.
- Every dashboard.py edit this session was verified with `ast.parse()`
  before writing/committing, per the existing guardrail. No schema.sql
  edits this session beyond step 1 (which got its own dedicated
  pre-flight semicolon-in-comment check, and still needed one fix --
  see below).
- **Repeated the semicolon-in-comment schema.sql bug** (the one that's
  bitten this project 3+ times now) on the very first schema change of
  this session, despite an explicit pre-session warning about it and a
  claimed grep pass beforehand. `ValueError: not an error` on
  `init_schema()`, root cause a stray `;` inside a `--` comment. Fixed,
  re-verified live. **This is now 4 times.** Worth considering whether
  the pre-flight check needs to be an actual executable check (run the
  naive `.split(';')` against the real text programmatically) rather
  than a self-reported "I grepped it" claim, since eyeballing has now
  failed repeatedly on exactly this failure mode.

## Immediate next steps (before opening the PR)

1. **Regenerate `docs/AST_OUTLINE.md` and `docs/FILE_TREE.txt`
   locally** via the pre-commit hook / `scripts/run_hooks.sh` -- every
   commit this session went through the GitHub API, which bypasses
   local hooks, so these are now stale relative to the actual code.
2. **Open the PR** for `workspace/subsystem-foundation` -> `main` once
   the docs are regenerated and committed. User reviews and merges it
   themselves per standing instruction -- Claude does not merge.
3. Nothing else is blocking; the five-step Workspace foundation slice
   is functionally complete and click-tested.

## Still open / not started

- Step 5 from the previous handoff: DOCX export. Still open, still not
  next -- no work happened on it this session.
- The two deferred roadmap items above (palette system, Layouts 2/3).
- The export-report two-click navigation gap (deferred, not forgotten).
