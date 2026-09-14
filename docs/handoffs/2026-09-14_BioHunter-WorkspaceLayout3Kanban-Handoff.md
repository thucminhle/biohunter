# Handoff: Workspace Layout 3 (Kanban) + Layout 1 fixes

**Session date 2026-09-14, following up on
`2026-09-13_BioHunter-WorkspaceSubsystemFoundation-Handoff.md`.**

## Branch / PR status — check this first

`workspace/subsystem-foundation` is still the active branch. **PR #8** (the
foundation work: settings table, sort param, visual refresh, Layout 1) was
already reviewed and merged into `main` mid-session. All work described in
this handoff happened *after* that merge, on the same branch, and is in a
**second, still-open PR — #9** (https://github.com/thucminhle/biohunter/pull/9).

If PR #9 has been merged by the time you read this, work from `main`. If it
hasn't, do not build on top of it without checking with the person first —
same rule as last time. Branch tip as of this handoff: `a33f040`.

## What shipped this session

### Layout 1 (master-detail) — two real bugs fixed, not just polish
The previous handoff's Layout 1 had two live bugs, found via actual daily
use (not code review):
1. The filter form had no hidden field for `selected`, so applying any
   filter while in split view silently bounced you back to the grid.
   Fixed in `_filter_bar_html()`.
2. `.dash-wrap` was hard-capped at 1080px on *every* page, wasting a lot of
   horizontal space. Confirmed with the person this should apply
   everywhere, not just split view — widened globally: `.dash-wrap` to
   1600px, `.dash-wrap--wide` (the token-usage tables) to 1800px so it
   stays genuinely wider than the default.

### Layout 3 (Kanban) — full build, out of roadmap order
**Note the sequencing deviation:** the roadmap's Workspace section says to
ship Layout 2 before Layout 3. The person explicitly chose to do Layout 3
first after seeing both specs, so Layout 2 (data-dense table + slide-over
drawer) is still **completely unstarted** — see "Next up" below.

Architecture, per the roadmap's own principle (one shared filtered/sorted
data layer, interchangeable layout renderers):
- `_filtered_postings()` gained `include_stale: bool = False`. Every
  existing caller's behavior is byte-identical by default (verified with a
  standalone SQLite equivalence test, not just read by eye) — Kanban is the
  only caller that passes `True`, since a "Stale" column is its whole
  premise and this function otherwise always excludes stale postings.
- `dashboard_settings.layout_mode` — this table/module has existed since
  the foundation work but was **never actually wired to anything** until
  now. `_page()` now reads it on every page load and renders a Grid/Kanban
  toggle in the topbar; `POST /dashboard-settings/layout-mode` persists it;
  `index()` branches to `_kanban_page()` when it's `"kanban"`.
- `_kanban_page(conn, filters)` — reuses the exact same `_filter_bar_html()`
  and `_filtered_postings()` as Grid. 6 columns (see Prepared below),
  cards link to the standalone `/postings/<id>` detail page (not the
  Grid-specific split view), has-draft/quality badge shown on every card
  regardless of column.
- Drag-and-drop is real HTML5 drag events (no framework), **instant move**
  (chosen explicitly over a full-page reload) via `POST
  /postings/<id>/status`, reverting the card + alerting on write failure.
- `_set_posting_status()` — added as the single write path for status
  changes. `mark_stale_route()` (the existing "Mark as stale" button) was
  refactored to call it too, so the button and Kanban's drag-to-Stale can
  never diverge on `stale_at` handling.

### The "Prepared" column — a hybrid design, added mid-session by request
The roadmap explicitly said has-draft should be a card *badge*, not a
column, reasoning that draft status and application status are orthogonal
facts about a posting. The person asked for a dedicated column anyway. The
resolution that came out of that conversation, worth preserving as
precedent:

- **Prepared is earned, never dragged.** `_maybe_promote_to_prepared()` is
  the *only* place that ever sets `status = 'prepared'` — called right
  after `drafts_db.save_draft()` succeeds, from both `generate()` and
  `batch_generate()`'s job functions.
- It **only fires from `new` or `scored`.** Regenerating a draft for a
  posting that's already `applied`/`rejected`/`stale` leaves its status
  untouched — the app never silently reclassifies something a person
  already acted on by hand.
- `DRAG_TARGET_STATUSES` (everything except `prepared`) is what
  `update_posting_status_route()` actually validates drag-and-drop writes
  against, kept separate from `POSTING_STATUSES` (the full valid-value set,
  which does include `prepared`). `kanban.js` also blocks the drop
  client-side with an explanation before it ever reaches the server.
- The has-draft/quality badge still appears on cards in *every* column —
  an `applied` posting can still show it has a draft. The orthogonality the
  roadmap cared about is preserved everywhere except this one earned
  auto-transition.
- `migrate_backfill_prepared_status.py` (new root-level script, matching
  the existing `migrate_*.py` convention) one-time-promotes postings that
  already had a draft *before* this shipped, since the auto-promotion only
  fires on new draft-generation events going forward. Idempotent — verified
  with a standalone SQLite test, safe to re-run.

### schema.sql
One-line comment change only (`postings.status`'s value-list comment now
includes `prepared`) — no column/constraint change, since `status` has no
DB-level `CHECK`. Given this file's documented history (the semicolon-in-
comment bug has bitten it 4 times), this was verified with an actual
executable pre-flight check before committing, not by eye:
- naive-splitter (`text.split(';')`, no comment-stripping — same
  unsophisticated approach `db.py`'s real splitter uses) statement count
  confirmed unchanged
- scanned every comment line for a literal `;` — zero found
- the **entire schema was actually executed** against a real in-memory
  SQLite DB (all `CREATE TABLE` statements ran successfully), not just
  parsed or counted

This is the "real pre-flight check" the previous handoff said this project
needed instead of eyeballing/grepping. It exists now as a repeatable
pattern (see the PR description for the actual script) — worth reusing
verbatim for any future schema.sql touch, not reinventing each time.

## Process lessons for whoever works this branch next

- **Docs regen requires the person's local machine.** `docs/AST_OUTLINE.md`
  and `docs/FILE_TREE.txt` are regenerated by `scripts/run_hooks.sh` calling
  `scripts/generate_outline.py`. Every commit an AI session makes via the
  GitHub API bypasses this local pre-commit hook, so these docs silently go
  stale after *any* API-based commit — not just once, it happened again
  this session after the foundation PR merged. If you're committing via API
  (not the person's local git), assume these are stale by the time you're
  done and ask the person to regenerate + commit before opening/updating a
  PR, the same way this session did it twice.
- **Both scripts are now actually tracked in git** (`scripts/run_hooks.sh`,
  `scripts/generate_outline.py`) — they weren't before this PR, because
  `scripts/` was gitignored. That gitignore entry was removed this session.
- **`.gitignore` still has a stray bug**, unrelated to the above, never
  fixed: line with `{src/` (a literal brace character) instead of `src/`.
  Currently harmless by accident — gitignore doesn't do brace expansion, so
  this pattern matches nothing. If anyone "corrects" it to `src/`, it would
  silently gitignore the entire source tree. Flagged, not fixed — low
  priority but worth fixing deliberately rather than by accident.
- **The person is still building Git fluency.** They're on VS Code, and
  since AI sessions can push directly to GitHub, their local checkout falls
  behind without any local signal that it happened. If you're another AI
  session working via the API (like this one), expect to walk them through
  `git fetch` / `git status` / `git pull` explicitly and concretely — don't
  assume familiarity with terms like "fast-forward" or "diverged" without
  defining them plainly.
- **The "ask before assuming" pattern paid off repeatedly this session** —
  worth continuing deliberately, not just as a one-off: the person's
  one-line description of Layout 2 as "timeline" turned out to not match
  the roadmap's actual spec at all (turned out to be a stale in-code
  comment, now fixed); the Kanban entry mechanism and drag-and-drop write
  scope were both genuine open questions with real trade-offs, not details
  to silently pick. Layout 2's roadmap spec (below) is even thinner than
  Layout 3's was — expect to ask more, not less.

## Next up: Layout 2 (data-dense table + slide-over drawer)

The roadmap's entire spec for this, verbatim: *"Layout 2 — Data-dense table
with slide-over drawer (best fit for sorting/comparing drafts by score)."*
That's it — one line, no further detail. Unlike Kanban (which at least had
"columns = status, has-draft as a badge" to start from), this needs real
design conversation before any code, covering at minimum:
- Which columns, and are they sortable client-side or via a `sort=` param
  like the existing `_filtered_postings()` already supports?
- Does clicking a row open the drawer, or is there a dedicated action?
- Is the drawer read-only, or does it carry the same actions the standalone
  detail page has (Generate, Mark as stale, Delete)?
- Should it reuse the existing `_posting_detail_body()` helper inside the
  drawer, or does "data-dense" imply a deliberately more compact detail
  view than the full posting-detail page?
- Third layout-toggle option: `_page()`'s Grid/Kanban toggle is currently a
  2-button form. Adding a third (`table`) needs that markup and
  `dashboard_settings.layout_mode`'s accepted values extended together —
  small but touches shared code every layout depends on, so verify it
  doesn't regress the other two toggles.

Reusable pieces already in place for this: `_filtered_postings()`,
`_filter_bar_html()`, `_set_posting_status()` / `POSTING_STATUSES` /
`DRAG_TARGET_STATUSES` if the drawer wants quick status-change actions,
`_posting_detail_body()` for whatever the drawer ends up showing.

## Still deferred, unchanged from before

- **10-palette CSS system** — genuinely low priority per the person's own
  read; only worth doing if the single default look is still bothering
  them once there's more mileage on the app.
- **Export report's two-click nav-back** — small nav polish, not urgent.
- **DOCX export** (original Writer/Critic roadmap, Step 5) — still fully
  open. This is now the third session in a row it's been deferred in favor
  of Workspace work, by the person's own explicit prioritization each time,
  not an oversight — but worth surfacing plainly rather than letting it
  quietly age further.
