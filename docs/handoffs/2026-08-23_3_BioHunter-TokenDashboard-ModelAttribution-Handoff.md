# BioHunter — Token Usage Dashboard: Per-Run Rework + Model Attribution, Confirmed Live

**Session date:** 2026-08-23 (fourth session this date). Builds on two
prior same-day handoffs:
`2026-08-23_BioHunter-CaptainBatchGeneratePersistedJobs-Handoff.md`
(named the token dashboard as an interrupted task) and
`2026-08-23_2_BioHunter-TokenUsageDashboard-Handoff.md` (built the
first working version — by-kind-only totals, two real bugs fixed along
the way). **This session's work happened in TWO parts, worth
understanding separately:**

1. The user had a **different AI session** independently rework
   `dashboard.py`'s token-usage feature into a proper per-run view
   (see Section 1) while this thread wasn't active.
2. This thread then added **model attribution** on top of that other
   AI's version, without reverting any of its work (see Section 2).

Both parts are now merged into one file and confirmed live together.
Read this doc's Section 1 even if you were "the AI that built the
per-run view" in spirit — the version described here is the one
actually in the user's repo now, verified against their real upload,
not assumed from memory of any single session.

---

## 1. What the other AI's session built (per-run rework)

Replaced the original by-kind-only aggregate (`/tokens` showing just
"generate: 1 run, 50,909 tokens") with a real per-run table. Schema
additions to `run_log`:

```
job_id            TEXT     -- links back to the `jobs` table's own id
prompt_tokens     INTEGER  -- split out from the old single tokens_used total
completion_tokens INTEGER  -- (needed to compute tok/s the same way live badges do)
llm_seconds       REAL     -- LLM generation time only, summed across calls
duration_seconds  REAL     -- real wall-clock job time (includes Qdrant/DB work too)
```

`tokens_used`/`cost_usd` (the original two columns) are kept —
`tokens_used` still holds the same grand total, `cost_usd` still NULL
(no pricing table exists).

Code additions in `dashboard.py`:
- `_log_token_usage(kind, job_id, duration_seconds=None)` — gained the
  `duration_seconds` param, and writes all five new columns per row.
  Callers in `_run_generation`/`_run_batch_generation`/
  `_run_score_batch` now measure `time.time()` around their own run and
  pass it through.
- `_format_duration(seconds)`, `_TOKEN_RUN_KIND_LABELS` (dict mapping
  job kind → display label), `_token_run_results_html(kind, job_data)`
  (renders a link to what the run actually produced — a posting detail
  page for generate, a results page for score_batch — by reading the
  job's full JSON out of the `jobs` table via `run_log.job_id`).
- `/tokens` rebuilt: a summary strip (runs logged / total tokens /
  overall avg tok/s, computed over the WHOLE table) above a per-run
  table (date, job kind, duration, tokens, avg tok/s, results link),
  capped at the 100 most recently finished runs.

This is a genuinely better design than the by-kind-only version this
thread originally shipped — one row per actual run, with a link back
to what it produced, rather than an opaque running total. Kept as the
foundation; nothing from it was reverted this session.

## 2. What THIS session added on top (model attribution)

The other AI's rework, like the original version, still discarded
`LLMResponse.provider`/`.model` (both always set by every backend in
`llm.py`, unlike token counts which are best-effort) — so the per-run
table showed duration/tokens/tok-s but not WHICH model produced them.
Added without touching anything from Section 1:

- **`schema.sql`** — one more `run_log` column: `model TEXT`. Comma-
  joined if a job's calls ever span more than one distinct model (not
  the case today — every role in `config/roles.yaml` maps to one model
  per job kind — but not assumed).
- **`_make_usage_callback`** — now also accumulates `models_used`, a
  list (JSON-safe, since job dicts persist as JSON) of every distinct
  `"<provider>/<model>"` string seen across the job's calls.
- **`_log_token_usage`** — joins `models_used` with `", "` and writes
  it into the new `model` column. Function signature unchanged, so all
  three existing call sites needed zero edits.
- **`/tokens`** — added a **Model** column to the per-run table, plus a
  new **"By model"** summary section (runs + total tokens per distinct
  model), sourced from a `GROUP BY model` query. Rows logged before
  this migration show `(unknown model)` — visible, not dropped.
- **New migration: `migrate_add_run_log_model.py`** — separate from
  whatever migration the other AI's session used for the five per-run
  columns (that one wasn't part of this thread's context, so this
  script doesn't assume its name — it only adds `model`, and warns
  loudly rather than failing if the five prerequisite columns aren't
  present yet, in case that earlier migration hasn't run in this
  environment).

## 3. Confirmed live this session

User ran **one `generate` job** (single posting) against the fully
merged file and confirmed the LLM model name showed up correctly in
the `/tokens` per-run table.

**NOT yet re-confirmed under the new schema** (was confirmed under an
earlier, different version of `/tokens` in the prior same-day session,
but not re-checked after this session's merge):
- `batch_generate` — model attribution across a multi-posting batch
  (all postings in one job share one `job_id`/`run_log` row; confirm
  the model column populates correctly there too, not just for a
  single generate).
- `score_batch` — same, for the `scorer_fit` role.
- Concurrent jobs (e.g. generate + score_batch at once) — confirmed
  correct isolation under the OLD by-kind-only version two sessions
  ago; worth a quick re-check under the per-run + model version, though
  there's no structural reason it would have broken (each job's
  `_make_usage_callback` closure is still keyed to its own `job_id`).
- The "By model" summary table's totals, once more than one run exists
  in history — only tested with a single fresh run so far.

## 4. Known gaps, stated deliberately

- **`cost_usd` still NULL everywhere.** No per-model $/token pricing
  table exists in this codebase. Smallest addition if wanted: a static
  `config/model_pricing.yaml` keyed by the same `provider/model`
  strings `run_log.model` already stores, multiplied against
  `prompt_tokens`/`completion_tokens` in `_log_token_usage()`.
- **No date-range filtering on `/tokens`** — same gap the per-run
  rework already had; the summary strip aggregates the whole table
  regardless of the 100-row display cap, so cumulative totals stay
  accurate as history grows, but there's no "this week" view.
- **`OpenAICompatibleClient`'s usage/model reporting is unverified**
  against a real MLX/oMLX server (long-standing caveat in `llm.py`,
  predates this session). `.model`/`.provider` themselves are always
  set regardless (they come from the request, not the response), so
  model attribution specifically should be fine even there — only
  token counts are at risk of coming back `None` on that backend.
- **Two independent AI sessions edited the same file this date** — the
  merge went cleanly and is confirmed live, but if anything looks off,
  diff against both `2026-08-23_2_...`'s version (by-kind-only) and
  whatever the other AI session's own transcript shows, since this
  thread only ever saw the OTHER session's *output* (the uploaded
  file), never its reasoning or full diff.

## 5. Standing open items, carried forward unchanged

Per `2026-08-23_2_...`'s own Section 4 (itself carried forward from
`2026-08-23_...`'s Captain session) — none of this was touched in
either part of this session:

- Captain roadmap items #3 (unified progress-bar contract), #4
  (combine Scout + dead-link-check into one job), #6 (index-page
  Generate-button in-flight-check bug) — still open, still needs a
  fresh read of `docs/ROADMAP.md`'s current exact wording.
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

## 6. Working style — unchanged, with one addition

Vibe-coded: files uploaded to chat, edited, downloaded, dropped into
the local repo by hand. Every code change handed back as a **complete
file**, never a diff or snippet. Restart the dashboard process after
any `.py` edit; run any new `migrate_*.py` script once before
restarting after a schema change.

**New this session, worth keeping:** when two AI sessions (or an AI
and manual edits) touch the same file in parallel, hand the LATEST
uploaded copy of that file back to whichever AI does the next edit —
don't let an AI edit from its own memory of a file it built earlier,
since that's exactly how the two-versions-of-`/tokens` situation this
session had to reconcile came about. Re-uploading the current file
before every edit request is the reliable pattern.

## 7. How to pick this up

1. Read this doc in full before touching anything.
2. Confirm the migration ran:
   `python migrate_add_run_log_model.py` (safe to re-run, no-ops if
   already applied).
3. Run `pytest tests/ -v` to confirm nothing regressed.
4. Re-confirm the three NOT-yet-checked items in Section 3
   (batch_generate model attribution, score_batch model attribution,
   concurrent-job isolation) before trusting them.
5. If picking up cost tracking or date-range filtering, start with
   Section 4's notes on the smallest viable addition for each.
6. Otherwise, resume wherever Section 5's carried-forward items point.

---
*(End of handoff — paste everything above this line into a new chat.)*
