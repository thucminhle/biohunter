# BioHunter — Batch Generation, Job Cancellation, and Persisted Job History Built; Captain Subsystem Partially Addressed

**Session date:** 2026-08-23. Started as "scope and build Captain" per the
2026-08-14_2 four-subsystem plan, but was redirected by explicit user
request into something more concrete: sequential multi-select batch
generation, then everything real usage showed was needed to make that
safe to actually use (cancel, real job visibility, persistence). This
is named explicitly because it's NOT what Captain was originally
scoped as in `docs/ROADMAP.md` — some Captain items got built as a
side effect, others weren't touched at all. See Section 3.

**Why this doc exists:** a lot happened in one long session, driven by
real live usage rather than a single up-front design pass. This hands
over exactly what's built + confirmed, what's built but NOT yet
confirmed live, and what Captain-adjacent work is still open.

---

## 1. Built and confirmed live this session

- **Multi-select batch generation.** Checkboxes on postings-index
  cards → "Generate selected (N)" button → a confirmation page
  (`batch_generate_confirm`) listing exactly what will run, flagging
  already-drafted postings with a note (still checked by default, your
  call to uncheck) and excluding description-less postings entirely
  (listed read-only) → `POST /postings/batch-generate/start` spawns
  `_run_batch_generation`, which runs postings **sequentially** (one at
  a time — protects the local model's KV cache; parallel execution is
  an explicitly deferred future option, not built). A per-posting
  failure is caught, recorded, and the batch continues to the next one
  rather than stopping. **Confirmed live**: real run against two real
  postings, both resume + cover letter generated successfully.
- **Cancel support**, added incrementally across the session:
  - `score_batch`, `scout`, `dead_link_check` — each has a real Python
    loop `dashboard.py` controls directly; a `cancel_requested` flag is
    checked between items (between postings / companies / URLs). **User
    confirmed live for all three.**
  - `scout` specifically required a change to `detector.py`:
    `run_scout()` gained an optional `should_stop: Callable[[], bool]`
    param, checked once at the top of each company's loop iteration —
    same boundary `on_company_done` already fires at. Optional,
    defaults to `None`, zero behavior change for any existing caller
    that doesn't pass it.
  - Single-posting `generate` — no Python loop to check between
    iterations here (`run_revision_loop()` is one blocking call), so
    cancellation is raised from *inside* the `on_step` callback instead
    (a new `_JobCancelled` exception, caught in `_run_generation`'s
    `try/except`, no draft saved on cancel). **Partially confirmed**:
    `revision.py` (uploaded this session) shows its own two direct
    `on_step("round N: critique")` calls are bare, no try/except, so
    raising there propagates cleanly. The other ~9-per-round `on_step`
    calls happen inside `generate_draft()` in `writer.py` (not uploaded
    this session) — whether those specifically let the exception
    through is still **not traced**, though the user's latest message
    ("I can cancel mid-run on the job posting") suggests it works in
    practice. Worth an explicit re-confirmation next session naming
    which job kind was actually tested, since the prior message only
    explicitly named score_batch/scout/dead_link_check.
  - Cancel is a *request*, never an interrupt, for every kind — the
    item currently in flight (an LLM call, an HTTP check, a company's
    fetch) always finishes; only the *next* one is skipped.
- **Recent Jobs (`/jobs`) rewritten.** Real human-readable labels
  instead of the bare job-id hex string, via a new `_job_display()`
  helper — single source of truth used by both `jobs_index()` and
  `job_status_page()`. Live per-kind detail (e.g. score_batch shows "X
  scored, Y skipped, of Z — currently: ...", not just "running"). The
  page auto-refreshes every 4s while anything's active. **Fixed a
  pre-existing bug** while in there: the list was sorted by the raw
  job-id hex string, which has no chronological meaning (job ids are
  random) — now sorted by a real `created_at` timestamp stamped on
  first `_set_job()` call for that job.
- **Persisted job history.** New `jobs` table in `schema.sql` (id,
  kind, status, `data_json` — the full job dict as JSON, same "one
  blob column" pattern `drafts.result_json`/`run_log.detail` already
  use). Every `_set_job()` write now also upserts to this table via
  `_persist_job()` (best-effort — a persistence failure is logged, not
  raised, so in-memory state is never lost over a DB hiccup). On
  startup, `main()` calls `_load_jobs_from_db()` to repopulate the
  in-memory `_jobs` dict. **This REVERSES dashboard.py's own prior
  stated decision** ("nothing here needs to survive a process
  restart") — named explicitly in the module docstring rather than
  left as a silent behavior change.
  - Any job that was still `queued`/`running` when the *previous*
    process stopped is rewritten to a new terminal status,
    `interrupted`, at load time (both in memory and written back to the
    DB) — its background thread doesn't exist in the new process, so
    leaving it `running` would show a live-looking progress bar that
    will never move again. `_job_display()` has explicit `interrupted`
    branches for every job kind, using only the fields that are
    actually guaranteed to have been written incrementally (e.g.
    scout's `companies_done`/`total_companies`, NOT `companies_checked`/
    `new_postings`, which are only ever written in the post-loop
    summary code that an interrupted job never reached).
  - **NOT yet confirmed live**: an actual dashboard restart mid-run,
    checking that the interrupted job shows up correctly. The user
    confirmed "I can view past runs" (persistence itself works,
    survived at least the session), but not specifically the
    interrupted-status path.
- **Delete / Clear job history.** Every finished job gets a Delete
  button; a "Clear all history" button removes every finished job at
  once. An active (queued/running) job is never deletable — the
  buttons simply don't render for it, since deleting the DB row out
  from under a live background thread would just have it silently
  reappear on the thread's next `_set_job()` call. **Not yet confirmed
  tested live.**
- **Draft-status filter.** New "Draft status: Any / Has draft / No
  draft yet" dropdown in the postings-index filter bar, applied inside
  the shared `_filtered_postings()` helper so both `index()` and
  `score_batch_route()` honor it consistently (same "one filter
  implementation, two callers" pattern the 2026-08-10 handoff
  established). **Not yet confirmed tested live.**
- **Fixed a real UI bug** found while working on the above: the
  generic job-status page's Cancel button was being injected
  client-side for ANY job kind/status combination regardless of
  whether the job was actually still active — moved that check
  server-side so a finished job never shows a live Cancel button.

## 2. Answered this session, no code changes

- **"Does Regenerate delete the previous resume/cover letter?"** No.
  `drafts.save_draft()` always inserts a NEW row — the old draft is
  never deleted or overwritten, it's just not shown anymore (the UI
  only ever displays the latest draft per posting). There's currently
  no UI to browse older drafts if you wanted to compare — a possible
  future feature, not built.
- **"Why did score_batch skip more than it scored?"** Not a bug — by
  design, mirrors `cli.py`'s own `score-postings` semantics. With
  "Include already-scored (rescore)" unchecked, it skips anything whose
  `status != 'new'` (i.e. already scored in a prior run) plus anything
  with no stored description. If you've scored roughly the same
  filtered set before, a second run without rescore will skip nearly
  all of it — expected, not an error. Check "rescore" to force
  everything through.

## 3. Captain roadmap items — actual status after this session

The original `docs/ROADMAP.md` "Four dashboard subsystems" section
named six checkboxes for Captain. Status after this session (this
session did NOT re-read the roadmap file at the end to double check
exact wording — next session should re-read it fresh rather than trust
this summary for anything precise):

1. **Persisted job queue** — ✅ done (this session, `jobs` table).
2. **Multi-select batch generation** — ✅ done (this session).
3. **Unified progress-bar contract every job type implements once** —
   ❌ NOT done. `batch_generate` has real dual `<progress>` bar
   elements on its own dedicated page; `generate`/`score_batch`/
   `scout`/`dead_link_check` still share the older generic
   spinner-wrap page, which shows text-only detail lines, no actual
   bar element. `_job_display()` unifies the *text*, not the *visual*
   progress representation — a real gap still open.
4. **Combine "Run Scout" and "check for dead links" into one job** —
   ❌ NOT touched this session.
5. **Job history becomes a permanent page backed by the persisted
   queue** — ✅ done (this session).
6. **Supersedes the index-page Generate-button in-flight-check bug**
   — ⚠️ UNCLEAR. The roadmap named this as something that'd get fixed
   as a side effect of item #3 (the unified progress contract). Since
   #3 wasn't done, this is presumably still open too, but the exact
   bug description wasn't preserved in this session's context — next
   session needs to re-read the roadmap section directly for the exact
   wording rather than rely on this summary.

## 4. Known limitations, stated plainly (not bugs, just scope)

- Batch-generate checkbox selection only applies to postings shown on
  the CURRENT PAGE of the index — pagination isn't select-all-aware.
  Stated when built, still true.
- Single-posting generate's cancel mechanism depends on an assumption
  about `writer.py`'s `generate_draft()` internals that's still
  unconfirmed (see Section 1). It appears to work per the user's most
  recent message, but the exact mechanism (which of the 10 on_step
  calls per round actually let the exception through) isn't fully
  traced.
- `jobs.data_json` stores each job's full in-memory dict as-is — the
  shape differs by kind (see `_job_display()` for what each kind
  actually writes). This is fine for the current read pattern
  (deserialize whole, look at known keys) but would need a real
  migration if a future feature wanted to query across job kinds by a
  shared field.

## 5. Standing open items, carried forward unchanged (unrelated to Captain)

Per the last real look at these (2026-08-17_2 handoff, itself carrying
these forward from earlier still) — none of this was touched this
session, no evidence any of it has changed:

- Scribe Therapeutics's Greenhouse board 404 situation — may actually
  be moot now given the dead-link-check Greenhouse-redirect fix from
  2026-08-13, but that fix was built around Nurix's dead-posting
  pattern specifically; worth a fresh, explicit look rather than
  assuming it also covers Scribe's whole-board 404 case.
- Lever (Mammoth Biosciences) dead-link detection — genuinely
  unverified, no evidence gathered either way.
- "Example Biotech Inc" stale test entry — still sitting in the DB.
- `is_posted: false` filtering — still open.
- `cli.py`'s lack of PDF/stability wiring — still open.
- The MVP verification punch-list (candidate name in PDF, strict/loose
  stability, inline bold rendering, word-diff view, dashboard-link
  footer, browser notifications) — meant to be clicked through by the
  user directly, still no evidence it's happened.

## 6. Working style — unchanged

Vibe-coded: files uploaded to chat, edited, downloaded, dropped into
the local repo by hand. Every code change handed back as a **complete
file**, never a diff or snippet. Explain rationale before coding.
Restart the dashboard process after any `.py` or `schema.sql` edit —
`init_schema()` runs the whole schema file idempotently
(`CREATE TABLE IF NOT EXISTS`), so a plain restart is enough to pick up
the new `jobs` table, no separate migration step. Verify against real
live checks before claiming something works; state clearly what's
confirmed vs. not yet tested. Give explicit click-by-click / copy-paste
terminal steps — the user is not comfortable improvising in DevTools or
the command line.

## 7. Files to upload next session

**Must-have, regardless of what gets tackled:**
- This handoff doc
- `docs/ROADMAP.md` (to get the EXACT current wording on Captain items
  #3/#4/#6, rather than trusting Section 3's summary above)
- Current `dashboard.py` (this session's final version — job
  persistence, cancel across all five kinds, batch generation, draft
  filter)
- Current `schema.sql` (this session's version, with the new `jobs`
  table)
- Current `detector.py` (this session's version, with `should_stop`)

**Likely relevant depending on direction:**
- `writer.py` — if pinning down exactly how/whether `generate_draft()`
  lets the single-posting cancel exception through (Section 1's open
  item)
- `cli.py` — if tackling the standing "lack of PDF/stability wiring"
  item
- `scout/scraper.py` — if investigating Scribe's Greenhouse 404 or
  Lever dead-link detection

**Not needed:** anything Writer/export-specific beyond `writer.py`
itself (`llm.py`, `resume_pdf.py`, `settings_db.py`), or
Scout-ingestion-specific config (`companies.yaml`, `ats/` adapters) —
Scout & ingestion has been closed since 2026-08-17, unaffected by this
session's work.
