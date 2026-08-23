# BioHunter — Token Usage Mini-Dashboard Built and Confirmed Live

**Session date:** 2026-08-23 (second session this date — follows
`2026-08-23_BioHunter-CaptainBatchGeneratePersistedJobs-Handoff.md`,
which named the token usage dashboard as an in-progress, interrupted
task at the end of that session). This session picked that up, finished
it, and fixed two bugs introduced along the way — see Section 2, worth
reading even though the feature is now confirmed working end to end.

---

## 1. Built and confirmed live this session

**Token usage / generation-speed tracking**, end to end from the LLM
call itself through to a dashboard page:

- **`llm.py`** — `LLMResponse` gained three new optional fields:
  `prompt_tokens`, `completion_tokens`, `elapsed_seconds` (plus derived
  `.total_tokens` / `.tokens_per_second` properties). Populated
  best-effort per backend:
  - `AnthropicClient` — from the SDK's `response.usage.input_tokens` /
    `.output_tokens` (always present on a successful call).
  - `OllamaNativeClient` — from native `/api/chat`'s
    `prompt_eval_count` / `eval_count` / `eval_duration` (nanoseconds,
    generation-only — preferred over wall-clock for a true tokens/sec
    generation-speed number; falls back to wall-clock if the server
    doesn't report it).
  - `OpenAICompatibleClient` — from `usage.prompt_tokens` /
    `.completion_tokens` if the server sends them; **NOT confirmed
    against a real MLX/oMLX server** (same "not yet verified" caveat
    this module already carried for `json_mode`/`think` on this
    backend — nothing new, just now also applies to usage reporting).
  - All three: `None` (not `0`) when a server doesn't report usage —
    `LLMClient.__init__` gained an optional `usage_callback: Callable[[str
    role, LLMResponse], None] | None = None`, invoked after every
    successful `backend.chat()` call inside `complete()`. Best-effort
    (wrapped in try/except, logged not raised) so a broken callback can
    never take down an already-succeeded LLM call.
  - **Zero changes needed anywhere else** — `selection.py` (6 call
    sites), `critic.py` (1), `scorer.py` (1), `writer.py`, `revision.py`
    are all untouched. Every one of them only ever reads
    `response.text`, so adding fields to `LLMResponse` and an optional
    constructor kwarg to `LLMClient` is fully backward compatible.

- **`dashboard.py`**:
  - `_make_usage_callback(job_id)` — new helper, returns a closure that
    reads the job dict via `_get_job()`, adds this call's
    tokens/elapsed-seconds into running totals
    (`prompt_tokens_total`, `completion_tokens_total`,
    `llm_seconds_total`, `llm_calls_total`, `llm_calls_with_usage`), and
    writes them back via `_set_job()` — same read-modify-write pattern
    `_run_score_batch()`'s scored/skipped counters already used.
  - Wired into all three `LLMClient()` construction sites:
    `_run_generation`, `_run_batch_generation` (inside the per-posting
    loop — correctly accumulates across the WHOLE batch under one
    `job_id`, not just the last posting), `_run_score_batch`.
  - `_format_token_suffix(job)` — renders the `· 2,146 tokens (14
    tok/s)` line you can see on the Recent Jobs cards for any job kind
    that calls LLMs, used by `_job_display()`'s `generate`/
    `batch_generate`/`score_batch` branches.
  - `_log_token_usage(kind, job_id)` — writes ONE `run_log` row per
    finished job (`agent`=kind, `tokens_used`=total,
    `cost_usd`=NULL — see Known Gaps below), called at the end of all
    three job runners. Best-effort, same posture as `_persist_job()`.
  - New `/tokens` route + `tokens_dashboard()` view — aggregates
    `run_log.tokens_used` grouped by `agent` (job kind), shows runs
    logged + total tokens per kind + a grand total. Linked from the top
    nav bar next to Settings.

**Confirmed live** (screenshots this session): two jobs — a single
`generate` (AbbVie posting) and a `score_batch` (389 filtered
postings) — ran **concurrently**, both showed correct live token counts
and tok/s on their Recent Jobs cards while running, and both landed
correctly in `/tokens` after finishing:

| Job kind | Runs logged | Total tokens |
|---|---|---|
| generate | 1 | 50,909 |
| score_batch | 1 | 129,251 |
| **Total** | | **180,160** |

This also re-confirms (as a side effect, not the point of this session)
that concurrent job execution — named as confirmed in the prior
session's carried-forward notes — still works correctly with this new
code path added.

## 2. Bugs introduced and fixed THIS session — read before trusting old chat logs about this feature

The feature above works, but getting there took two real bugs, both
introduced by imprecise AI-authored instructions in an earlier part of
this same conversation, not by the user. Named explicitly so a future
session doesn't assume the whole thread's instructions were clean:

1. **`NameError` masking real successes as failures.** An early version
   of the run_log-logging code referenced a bare `job` variable that
   was never defined in scope in `_run_generation` /
   `_run_batch_generation` / `_run_score_batch`. In the first two, this
   exception was caught by the surrounding `try/except` and
   **overwrote an already-successful job's status to `"error"`** — the
   draft/scores had actually been saved correctly, but the dashboard
   reported failure. Fixed by replacing all three inline blocks with
   one correct shared helper, `_log_token_usage()`, that fetches the
   job dict properly via `_get_job(job_id)`.
2. **`/tokens` 500'd on a wrong function name**, then once fixed,
   **took down the ENTIRE dashboard** (every page, not just `/tokens`)
   because the shared page shell `_page()` unconditionally calls
   `url_for('tokens_dashboard')` in the nav bar on every render. The
   underlying cause: the `/tokens` route definition was pasted
   **after** `if __name__ == "__main__":` in the file, so
   `app.run()` started serving before Python ever reached the route
   registration below it — Flask never knew the endpoint existed.
   Fixed by moving the whole route to sit with the other `@app.route`
   definitions, immediately before `def main():`.

**Lesson for next session's instructions, stated plainly**: when
handing back Python edits for a large single file, either (a) do the
edit directly against the uploaded file and hand back a diff/full file,
or (b) if giving copy-paste instructions instead, give an exact anchor
line to paste after/before, not just "add this near X" — the ordering
mistake above (route placed after `if __name__`) would not have
happened with an explicit anchor.

## 3. Known gaps, stated deliberately (not solved by omission)

- **`cost_usd` stays `NULL`** in every `run_log` row this feature
  writes. There is no per-model $/token pricing table anywhere in this
  codebase. If real dollar-cost tracking is wanted, the smallest
  addition is a static `config/model_pricing.yaml` keyed by
  `provider/model` (e.g. `anthropic/claude-sonnet-5: {prompt: ...,
  completion: ...}`), multiplied against `prompt_tokens`/
  `completion_tokens` inside `_log_token_usage()`. Not built — no
  evidence yet that cost tracking (vs. just token volume) is actually
  needed.
- **`/tokens` aggregates by job KIND, not by role/branch.** You can see
  "score_batch used 129,251 tokens total" but not "how many of those
  were `scorer_fit` vs. something else" — there's currently only one
  role per job kind so this distinction doesn't matter yet, but
  `writer_selection` alone covers 8 different LLM branches inside a
  single `generate` job (see `writer.py`'s `generate_draft()`), and
  those aren't broken out. `_make_usage_callback`'s closure already
  receives `role` from `usage_callback(role, response)` and simply
  doesn't use it yet — the data needed for a per-role breakdown is
  already flowing, just not persisted/displayed at that granularity.
- **`OpenAICompatibleClient`'s usage reporting is unverified** against
  a real MLX/oMLX server, same caveat this module already carried for
  `json_mode`/`think` on this backend before this session. If a role
  ever routes through this backend in practice, check whether
  `prompt_tokens`/`completion_tokens` actually populate or silently
  stay `None`.
- **No date range or per-posting breakdown on `/tokens`** — it's a
  simple lifetime-cumulative-by-kind table. Fine for now, may want
  "this week" filtering once there's meaningfully more history in
  `run_log`.

## 4. Everything from the prior session's handoff — unchanged, not touched this session

Per `2026-08-23_BioHunter-CaptainBatchGeneratePersistedJobs-Handoff.md`
(same date, earlier session) — none of the following was revisited:

- Captain roadmap items #3 (unified progress-bar contract), #4 (combine
  Scout + dead-link-check into one job), #6 (index-page Generate-button
  in-flight-check bug) — still open, still needs a fresh read of
  `docs/ROADMAP.md`'s exact current wording rather than trusting any
  summary.
- Single-posting generate's cancel mechanism — still only "appears to
  work per user report," not fully traced through `writer.py`'s
  `generate_draft()` internals.
- Scribe Therapeutics Greenhouse-board 404 / Lever (Mammoth) dead-link
  detection — both still open, unverified either way.
- "Example Biotech Inc" stale test entry still in the DB.
- `is_posted: false` filtering — still open.
- `cli.py`'s lack of PDF/stability wiring — still open.
- MVP verification punch-list (candidate name in PDF, strict/loose
  stability, inline bold rendering, word-diff view, dashboard-link
  footer, browser notifications) — still no evidence of user click-
  through.

## 5. Working style — unchanged

Vibe-coded: files uploaded to chat, edited, downloaded, dropped into
the local repo by hand. Every code change handed back as a **complete
file**, never a diff or snippet, per standing preference — this
session's two bugs are a direct argument for sticking to that even more
strictly when editing a large shared file like `dashboard.py`: an
"add this snippet near X" instruction is exactly what went wrong twice.
Restart the dashboard process after any `.py` edit. Give explicit
click-by-click / copy-paste terminal steps.

## 6. How to pick this up

1. Confirm current `llm.py` and `dashboard.py` in the repo match what
   was handed back this session (`grep -n usage_callback
   src/biohunter/llm.py` should show 3 hits; `grep -n
   '@app.route("/tokens")' src/biohunter/dashboard.py` should show it
   BEFORE `def main()`, not after `if __name__`).
2. Run `pytest tests/ -v` to confirm nothing regressed.
3. If picking up the per-role token breakdown (Section 3, first gap):
   `_make_usage_callback`'s closure already gets `role` — start there.
4. If picking up cost tracking: start with a `config/model_pricing.yaml`
   design, not code, since the exact provider/model strings actually in
   use should come from the current `config/roles.yaml`, not guessed.
5. Otherwise, resume wherever Section 4's carried-forward items point.

---
*(End of handoff — paste everything above this line into a new chat.)*
