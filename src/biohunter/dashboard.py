"""
Local dashboard: browse Scout's postings, trigger Writer -> Critic ->
Revision generation for one posting at a time from the browser, review
the result, and export a plain resume/cover-letter PDF to actually
submit -- the "dynamic dashboard" ADR-0006 explicitly deferred
("revisit only once there's a concrete need"), built now on direct
request rather than by default.

Architecture, stated explicitly per this project's own working style
(name a real behavior/scope change, don't let it look like a small
addition): this module calls run_revision_loop()/diff_revision_result()
DIRECTLY -- the same functions cli.py's `report` command already
calls -- rather than shelling out to the CLI as a subprocess. One
pipeline implementation either way (writer.py/critic.py/revision.py
are unchanged and untouched by this file); this just skips the extra
process boundary a subprocess approach would have added.

Single local Flask process, single user, no auth -- this runs on your
own machine, it is not a deployed service, and nothing here should be
exposed past localhost. Generation takes real minutes against local
Ollama models, so it NEVER runs on the request thread: POST
/postings/<id>/generate starts a background thread and returns
immediately with a job id; the browser polls /jobs/<job_id>.json until
it's done, matching the "don't hang the tab for a multi-minute LLM
run" reasoning from the design discussion that led to this file.

A crashed/restarted dashboard process loses any IN-FLIGHT (not yet
completed) generation -- completed ones are already durably persisted
via drafts_db.py by the time a background thread finishes, so nothing
that finished is ever lost, only a run that was still running.

Run with: python -m biohunter.dashboard [--port 5050] [--debug]

New dependency: `pip install flask`. PDF export (resume_pdf.py) needs
Playwright separately -- see that module's docstring.

2026-08-09 additions (postings-index filtering + manual entry): the index
route now supports keyword/location/company/date/score filtering and
pagination, and there's a manual-add flow (GET/POST /postings/manual) for
postings Scout didn't find on its own. Filtering reuses cli.py's
keyword_filter_match() and DEFAULT_BAY_AREA_LOCATIONS -- the exact
substring-matching logic list-postings already used -- rather than a
second, dashboard-only reimplementation of the same heuristic. Score
filtering is against postings.score (scorer.py's job-FIT score, run via
`biohunter score-postings`), NOT drafts.final_score (Critic's resume-
quality score, which only exists after a draft has been generated) --
see the 2026-08-09 handoff for why those are two different things.

2026-08-10 addition (dashboard-triggered Scout + Scorer): REVERSES a
decision scorer.py's own docstring stated on purpose earlier the same
session ("like run_scout(), this is driven from the CLI... not from the
dashboard") -- naming that explicitly here rather than letting it happen
quietly as a side effect of adding a button. Both new routes reuse the
SAME background-job mechanism Generate already uses (_jobs/_set_job/
_get_job, a daemon thread, /jobs/<job_id>.json polling) rather than a
second mechanism -- the job dict now carries a "kind" field
("generate" | "score_batch" | "scout" | "dead_link_check") so job_status_page's polling JS
can show the right progress shape for each. Scout's "N of M companies
checked" progress (added once detector.py's run_scout() was actually
seen and confirmed to accept an on_company_done callback) uses the same
real-count approach score_batch already established -- not a fabricated
bar, an actual per-company count driven by run_scout()'s own callback.
"Score these N filtered postings" runs Scorer
over EXACTLY the postings-index's current filter set (same
keyword_filter_match() call the cards already render from, via a shared
_filtered_postings() helper extracted from index() for this) -- not a
second, separate filter UI, per the 2026-08-10 handoff's explicit
instruction.

2026-08-17 addition (Captain, item #2 only -- multi-select batch
generation): checkboxes on the postings-index cards + a "Generate
selected (N)" button -> a confirmation page (batch_generate_confirm)
listing exactly what will run, flagging any already-drafted postings
with a note (still checked by default -- your call to uncheck) and
excluding description-less postings entirely (listed read-only, since
batch has no per-posting paste step) -> POST /postings/batch-generate/
start spawns _run_batch_generation, which runs SEQUENTIALLY (one
posting at a time, protecting the local model's KV cache -- parallel
execution deferred until a beefier machine or a frontier API is in
play) using the SAME in-memory _jobs mechanism every other job kind
uses (explicit choice: a persisted job table is a separate future
session, not a dependency of this one). A per-posting failure is
caught, recorded, and the batch continues to the next posting rather
than stopping. New dedicated progress page (job_status_page's
"batch_generate" branch) shows two real progress bars (which posting;
that posting's own step/total_steps) plus a growing results list, not
just a final summary. A posting's single Generate button is blocked
while it's part of a running batch, mirroring the existing
single-generate in-flight check.

2026-08-23 addition (persisted job history): REVERSES this file's own
prior stated decision (see the "In-memory job registry" comment right
above _jobs' declaration, which said nothing here needs to survive a
restart) -- naming that reversal explicitly rather than letting it
happen quietly. Every _set_job() write now also upserts into a new
`jobs` table (schema.sql) via _persist_job(), so Recent Jobs survives a
dashboard restart. _jobs (the in-memory dict) is still the fast read
path for every request -- job_status_json's polling doesn't hit the DB
per poll, only writes do. On startup, main() calls _load_jobs_from_db()
to repopulate _jobs from the table; any job that was still
'queued'/'running' when the PREVIOUS process stopped is rewritten to a
new 'interrupted' terminal status (its background thread doesn't exist
in this process, so leaving it 'running' would show a live-looking
progress bar that will never move again). Delete/clear controls
(POST /jobs/<id>/delete, POST /jobs/clear) only ever remove
finished/cancelled/interrupted jobs -- an active job is never deletable
out from under its own running thread.

2026-08-23 addition, continued (Captain items #3 and #4): two more
roadmap items closed this same session, per direct request.

- **Unified progress-bar contract (#3).** A single new helper,
  _job_progress_fraction(job) -> float, computes a 0..1 completion
  fraction from whatever fields that job's kind already writes (no new
  per-kind state). Used in exactly two places, both server-side single
  source of truth: job_status_json() now returns a "progress_fraction"
  key alongside the raw job dict, and the generic spinner-wrap template
  in job_status_page() (previously text-only for generate/score_batch/
  scout/dead_link_check -- only batch_generate had a real <progress>
  element) now renders one <progress> bar whose value poll()'s JS sets
  from that same field, uniformly, instead of four kind-specific bar
  implementations. jobs_index() also renders a real bar per active job
  card now (previously text-only there too), and the page is now split
  into an "Active now" section (real bars, live progress) above the
  full "History" list, functioning as the multi-job mini-dashboard
  requested -- so someone who kicked off scout + score-batch + a
  generate batch together can see all three progressing at once
  without opening three tabs. Token usage / token generation speed
  were also requested for this mini-dashboard but are NOT built yet --
  llm.py hasn't been uploaded in this thread, so it's unknown whether
  the LLMClient response object even carries token counts (selection.py
  only ever reads response.text). Deferred, not forgotten -- see
  _job_progress_fraction()'s docstring for the intended extension point.
- **Combined Scout + dead-link-check job (#4).** New kind
  "scout_and_check", new route (POST /scout-and-check/run), new runner
  _run_scout_and_check_job(). Runs Scout to completion first (same
  on_company_done/should_stop mechanism _run_scout_job() already uses),
  then -- unless cancelled mid-scout -- immediately runs the dead-link
  sweep over every non-stale posting, same mechanism
  _run_dead_link_check_job() already uses. Deliberately duplicates
  those two functions' loop bodies rather than refactoring them to share
  code: both are already confirmed live from earlier this session, and
  the smaller/safer change here is new code alongside them, not an edit
  to a path that already works. The dead-link half's human-in-the-loop
  review gate is UNCHANGED -- this combined job still only ever
  populates the job dict's "dead"/"uncertain" lists; POST
  /postings/mark-stale, reached via dead_links_results() (now accepting
  kind "scout_and_check" too, not just "dead_link_check"), remains the
  only route that actually writes status='stale'. Explicit choice, not
  a default: a real dead-link sweep still runs at ~16% inconclusive per
  the first live run of that feature, and auto-marking stale without a
  person looking would risk quietly hiding postings that are still
  live. The postings-index "Run Scout" and "Check for dead links"
  buttons are replaced by one combined button; the two old routes
  (/scout/run, /postings/check-dead-links) and their runners are left
  in place, reachable directly, not deleted -- only the UI's default
  path changed.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import html
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

import yaml
from flask import Flask, Response, abort, jsonify, redirect, request, url_for

from . import drafts_db, settings_db
from .cli import DEFAULT_BAY_AREA_LOCATIONS, _log_run, keyword_filter_match
from .config import load_companies, load_search_criteria
from .critic import ScoreResult, parse_score
from .db import get_connection, init_schema
from .diff import diff_revision_result
from .llm import LLMClient
from .report import _STYLE as _REPORT_STYLE
from .report import _score_bucket, render_posting_report
from .resume_pdf import html_to_pdf_bytes, render_cover_letter_html, render_resume_html
from .revision import run_revision_loop
from .scorer import score_posting
from .scout import run_scout
from .scout.ratelimit import RateLimiter
from .scout.scraper import check_url_alive

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Index-page pagination -- the 693-posting screenshot that prompted this
# whole filtering pass rendered every card unpaginated; that only ever
# "worked" because nobody had scrolled to the bottom yet. Kept as a plain
# module constant, same spirit as cli.py's DEFAULT_REPORT_DIR, until
# there's a real reason to make it configurable.
POSTINGS_PER_PAGE = 60

_esc = html.escape

# ---------------------------------------------------------------------------
# Job registry. In-memory dict is still the live fast-path (every request
# reads from here, never the DB) -- but every write also persists to the
# `jobs` table (schema.sql) so Recent Jobs survives a dashboard restart.
# See the module docstring's 2026-08-23 entry for why this reverses what
# this comment used to say.
# ---------------------------------------------------------------------------

_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_ACTIVE_STATUSES = ("queued", "running")


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.setdefault(job_id, {})
        if "created_at" not in job:
            job["created_at"] = datetime.now(timezone.utc).isoformat()
        job.update(fields)
        snapshot = dict(job)
    _persist_job(job_id, snapshot)

def _make_usage_callback(job_id: str):
    """Returns a closure for LLMClient(usage_callback=...) that
    accumulates token/timing totals into job_id's dict, same
    read-modify-write-via-_set_job() pattern _run_score_batch() already
    uses for its scored/skipped counters. One closure per background
    job, not global -- so concurrent jobs (confirmed live this session:
    score_batch alongside scout_and_check) never cross-contaminate
    totals, and a batch_generate job's per-posting LLMClient() calls all
    correctly accumulate into the SAME batch job_id.

    Fields written, all cumulative across every llm.complete() call this
    job makes: prompt_tokens_total, completion_tokens_total,
    llm_seconds_total, llm_calls_total. Any single call whose response
    has None for tokens/elapsed (see llm.py's per-backend "best-effort"
    comment -- some MLX servers report no usage) simply doesn't add to
    the total rather than raising or reporting a fake 0; llm_calls_total
    still increments so the mini-dashboard can show "N calls (M with
    usage data)" instead of a silently-undercounted total.

    NEW 2026-08-23: also tracks `models_used`, a set (stored as a list --
    job dicts are JSON-persisted via _persist_job(), and JSON has no set
    type) of every distinct "<provider>/<model>" string seen across this
    job's calls. response.provider/.model are always set by every
    LLMBackend.chat() implementation (unlike the token/elapsed fields,
    which are best-effort), so unlike those fields this is never partial
    -- every call contributes its model, whether or not it reported
    usage numbers. _log_token_usage() below joins this list into
    run_log.model at the end of the job.
    """
    def _on_usage(role: str, response) -> None:
        job = _get_job(job_id) or {}
        prompt_total = job.get("prompt_tokens_total", 0)
        completion_total = job.get("completion_tokens_total", 0)
        seconds_total = job.get("llm_seconds_total", 0.0)
        calls_total = job.get("llm_calls_total", 0) + 1
        calls_with_usage = job.get("llm_calls_with_usage", 0)
        models_used = list(job.get("models_used", []))  # copy -- never mutate the stored list in place

        if response.prompt_tokens is not None:
            prompt_total += response.prompt_tokens
        if response.completion_tokens is not None:
            completion_total += response.completion_tokens
        if response.elapsed_seconds is not None:
            seconds_total += response.elapsed_seconds
        if response.prompt_tokens is not None or response.completion_tokens is not None:
            calls_with_usage += 1

        model_key = f"{response.provider}/{response.model}"
        if model_key not in models_used:
            models_used.append(model_key)

        _set_job(
            job_id,
            prompt_tokens_total=prompt_total,
            completion_tokens_total=completion_total,
            llm_seconds_total=seconds_total,
            llm_calls_total=calls_total,
            llm_calls_with_usage=calls_with_usage,
            models_used=models_used,
        )
    return _on_usage


def _log_token_usage(kind: str, job_id: str, duration_seconds: float | None = None) -> None:
    """Reads job_id's accumulated totals (written by _make_usage_callback()'s
    closure during the run) and writes ONE run_log row for the whole job.
    Fixes a bug in an earlier version of this function: that version
    referenced a bare `job` variable that was never defined in the
    calling functions' scope, which raised NameError, which the
    surrounding try/except then silently reclassified as a job failure
    -- even though generation/scoring had already succeeded. This
    version fetches the job dict itself via _get_job(), the same way
    every other read of job state in this file already does.

    duration_seconds: real wall-clock time for the whole job (caller
    measures this with time.time() around its own run, since that's
    precise and doesn't depend on any DB round-trip) -- distinct from
    llm_seconds below, which is LLM generation time only and is always
    <= duration_seconds. None (the default) writes NULL, same as every
    other field here when data isn't available -- matches this
    function's existing "don't fabricate a number" posture.

    NEW 2026-08-23: writes run_log.model as models_used (see
    _make_usage_callback()) joined with ", " -- almost always exactly
    one model per job today (every role in roles.yaml maps to one model
    per job kind), but joined rather than just taking the first entry
    so a future job that legitimately spans two models doesn't silently
    misattribute its tokens to only one of them. NULL (not an empty
    string) if models_used is empty, matching every other "no data"
    field in this function.

    Best-effort, like _persist_job(): a logging failure must never turn
    an already-successful generate/score run into a reported error.
    """
    job = _get_job(job_id) or {}
    prompt_tokens = job.get("prompt_tokens_total", 0)
    completion_tokens = job.get("completion_tokens_total", 0)
    llm_seconds = job.get("llm_seconds_total", 0.0)
    calls = job.get("llm_calls_total", 0)
    models_used = job.get("models_used", [])
    model_str = ", ".join(models_used) if models_used else None
    total_tokens = prompt_tokens + completion_tokens
    try:
        conn = get_connection()
        init_schema(conn)
        conn.execute(
            "INSERT INTO run_log (agent, finished_at, status, detail, tokens_used, cost_usd, "
            "job_id, prompt_tokens, completion_tokens, llm_seconds, duration_seconds, model) "
            "VALUES (?, datetime('now'), 'ok', ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                f"{calls} LLM call(s), {total_tokens:,} tokens",
                total_tokens or None,
                job_id,
                prompt_tokens or None,
                completion_tokens or None,
                llm_seconds or None,
                duration_seconds,
                model_str,
            ),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 -- logging usage must never mask a real success
        logger.exception("failed to log token usage for job %s (kind=%s)", job_id, kind)

def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def _persist_job(job_id: str, snapshot: dict) -> None:
    """Upserts the full current job dict into the `jobs` table. Called
    from _set_job() on EVERY write, including the frequent per-step
    ticks during a generation -- a local SQLite/libSQL write is well
    under a millisecond, and on_step/_on_company_done already call
    through get_connection() this often elsewhere in this file, so this
    isn't a new I/O pattern, just a new table it happens to also write
    to. Best-effort: a persistence failure is logged, never raised -- a
    job's in-memory progress (what every page actually reads) should
    never be lost just because a DB write hiccuped."""
    try:
        conn = get_connection()
        init_schema(conn)
        conn.execute(
            """INSERT INTO jobs (id, kind, status, data_json, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
                 kind = excluded.kind, status = excluded.status,
                 data_json = excluded.data_json, updated_at = excluded.updated_at""",
            (job_id, snapshot.get("kind", "unknown"), snapshot.get("status", "unknown"), json.dumps(snapshot)),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 -- persistence is best-effort, see docstring
        logger.exception("failed to persist job %s -- in-memory state is still correct", job_id)


def _load_jobs_from_db() -> None:
    """Repopulates the in-memory _jobs dict from the `jobs` table --
    called once from main(), before app.run(). Any job that was still
    'queued' or 'running' when the PREVIOUS process stopped is rewritten
    to 'interrupted' here (both in memory and written back to the DB):
    its background thread doesn't exist in this new process, so leaving
    it 'running' would show a live-looking progress bar and an active
    Cancel button for a job that will never move again. 'interrupted' is
    a distinct terminal status from 'cancelled' (a user's own choice) and
    'error' (a real exception) -- see _job_display()'s per-kind
    'interrupted' branches for how each kind explains this."""
    try:
        conn = get_connection()
        init_schema(conn)
        rows = conn.execute("SELECT id, data_json FROM jobs").fetchall()
    except Exception:  # noqa: BLE001
        logger.exception("failed to load persisted jobs -- starting with empty job history")
        return

    to_rewrite: list[tuple[str, dict]] = []
    with _jobs_lock:
        for job_id, data_json in rows:
            try:
                job = json.loads(data_json)
            except (TypeError, ValueError):
                continue
            if job.get("status") in _ACTIVE_STATUSES:
                job["status"] = "interrupted"
                to_rewrite.append((job_id, dict(job)))
            _jobs[job_id] = job

    for job_id, job in to_rewrite:
        _persist_job(job_id, job)

    logger.info("loaded %d persisted job(s), %d marked interrupted", len(rows), len(to_rewrite))



def _delete_job(job_id: str) -> bool:
    """Removes a job from history -- caller (delete_job_route) is
    responsible for confirming it isn't queued/running first; this
    function itself doesn't re-check, so it's not meant to be called
    directly from anywhere else without that same guard."""
    with _jobs_lock:
        existed = _jobs.pop(job_id, None) is not None
    try:
        conn = get_connection()
        init_schema(conn)
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
    except Exception:  # noqa: BLE001
        logger.exception("failed to delete persisted job %s", job_id)
    return existed


def _clear_jobs() -> int:
    """Clears finished job history. NEVER removes a job that's still
    queued/running -- its background thread is real and still writing to
    this same job_id; deleting the row out from under it would just have
    the next _set_job() call silently recreate it via setdefault(), so
    excluding active jobs isn't just a safety nicety, it avoids a
    confusing half-deleted state. Returns the number actually removed."""
    with _jobs_lock:
        to_remove = [jid for jid, j in _jobs.items() if j.get("status") not in _ACTIVE_STATUSES]
        for jid in to_remove:
            _jobs.pop(jid, None)
        remaining_ids = list(_jobs.keys())
    try:
        conn = get_connection()
        init_schema(conn)
        if remaining_ids:
            placeholders = ",".join("?" for _ in remaining_ids)
            conn.execute(f"DELETE FROM jobs WHERE id NOT IN ({placeholders})", tuple(remaining_ids))
        else:
            conn.execute("DELETE FROM jobs")
        conn.commit()
    except Exception:  # noqa: BLE001
        logger.exception("failed to clear persisted jobs")
    return len(to_remove)


class _JobCancelled(Exception):
    """Raised from inside on_step() to abort _run_generation()'s single
    blocking run_revision_loop() call from within -- the only kind of job
    in this file where cancellation can't be checked between discrete
    Python-level loop iterations, since there IS no loop here Python
    controls; run_revision_loop() itself calls on_step() once per unit
    of work and this is the only hook available.

    CONFIRMED PARTIALLY LIVE-VIABLE (2026-08-23, via revision.py): the
    two direct on_step("round N: critique") calls inside
    run_revision_loop() itself are bare, no try/except around them, so
    raising here from those specific calls WILL propagate cleanly. The
    other ~9-per-round on_step calls happen inside generate_draft()
    (writer.py, not uploaded this session) -- whether THOSE specifically
    swallow the exception is still unconfirmed. Worst case: Cancel on a
    single-posting generate only takes effect on the "critique" step of
    whichever round is running (1 of 10 steps) instead of the very next
    step -- delayed, not broken."""



def _active_generate_job_for_posting(posting_id: int) -> dict | None:
    """Returns the most recently started in-flight (queued/running)
    'generate' job for this posting, or None. Used by posting_detail()
    to show a live progress panel instead of the Generate button/form
    while a run it already knows about is still going -- previously the
    button just sat there unchanged with no indication anything was
    happening (2026-08-13 feedback).

    _jobs preserves insertion order (plain dict, Python 3.7+), so the
    LAST matching entry is the most recently started one -- relevant
    only if two jobs somehow got started for the same posting (not
    reachable via this UI, since the form disappears once one is
    detected, but a second browser tab or a race could still do it)."""
    with _jobs_lock:
        matches = [
            {"job_id": jid, **j} for jid, j in _jobs.items()
            if j.get("kind") == "generate" and j.get("posting_id") == posting_id
            and j.get("status") in ("queued", "running")
        ]
    return matches[-1] if matches else None


def _active_batch_job_for_posting(posting_id: int) -> dict | None:
    """Mirrors _active_generate_job_for_posting() but for kind='batch_generate'
    jobs (added 2026-08-17 for multi-select batch generation, see
    _run_batch_generation()'s docstring). Returns the batch job if
    posting_id is anywhere in its posting_ids list and the batch's
    OVERALL status is still queued/running.

    Deliberate simplification, confirmed with the user rather than just
    assumed: this blocks the single-posting Generate button for EVERY
    posting in the batch for as long as the batch is running -- even
    ones already finished earlier in the sequence. Revisit only if that
    turns out to be annoying in practice; the per-posting result is
    already visible in the batch job's own results list well before the
    whole batch finishes."""
    with _jobs_lock:
        matches = [
            {"job_id": jid, **j} for jid, j in _jobs.items()
            if j.get("kind") == "batch_generate"
            and posting_id in (j.get("posting_ids") or [])
            and j.get("status") in ("queued", "running")
        ]
    return matches[-1] if matches else None


@app.route("/jobs/active.json")
def jobs_active_json():
    """Powers the topbar's ambient job poller (see _page()'s <script>
    block) -- lets a generation keep running and notify you when it's
    done even if you've navigated to a completely different page,
    as long as some BioHunter tab is still open somewhere (no server
    push here, this is plain polling -- it cannot notify you if the
    browser itself is fully closed; see the module docstring's existing
    "in-flight work is lost on a process restart" note for the same
    kind of limitation, one level up).

    Returns every 'generate' job this process has seen, not just
    in-flight ones -- the client needs to see the done/error transition
    at least once to fire a notification, not just the running state."""
    with _jobs_lock:
        items = [{"job_id": jid, **j} for jid, j in _jobs.items() if j.get("kind") == "generate"]
    return jsonify(items)


@app.route("/jobs")
def jobs_index():
    """Lists persisted job history (the `jobs` table, schema.sql) --
    survives a dashboard restart as of 2026-08-23 (see module docstring's
    entry for that date; this used to say the opposite). Sorted by
    created_at, newest first -- NOT by job_id, which is a random hex
    string with no chronological meaning (a pre-existing quirk in the
    sort this rework also fixes, named here since it's a real behavior
    change, not just an addition).

    2026-08-23 rework, per real usage feedback:
    - job_id (a bare hex string) is no longer the visible title -- each
      kind now gets a human-readable label + a live detail line built by
      _job_display(), the SAME per-kind field names _run_score_batch()/
      _run_scout_job()/_run_dead_link_check_job()/_run_batch_generation()/
      _run_generation() already write, not a new data shape.
    - the page auto-refreshes every 4s while ANY listed job is still
      queued/running, so progress is visible without a manual reload --
      a plain page reload, not per-card JS patching, matching this
      project's stated preference for the smaller/simpler mechanism over
      a cleverer one for something this size.
    - a Cancel button appears next to any still-running job of a kind
      that can actually honor it (see cancel_job_route()'s docstring).
    - a Delete button appears on every FINISHED job (never an active
      one -- see _clear_jobs()'s docstring for why), plus a "Clear all
      history" button that removes every finished job at once, same
      active-job exclusion."""
    with _jobs_lock:
        items = sorted(_jobs.items(), key=lambda kv: kv[1].get("created_at", ""), reverse=True)

    active_items = [(jid, j) for jid, j in items if j.get("status") in _ACTIVE_STATUSES]
    history_items = [(jid, j) for jid, j in items if j.get("status") not in _ACTIVE_STATUSES]
    any_active = bool(active_items)
    any_finished = bool(history_items)
    _CANCELLABLE_KINDS = ("batch_generate", "score_batch", "dead_link_check", "scout", "generate", "scout_and_check")

    def _job_link(job_id: str, job: dict, show_bar: bool) -> str:
        status = job.get("status", "unknown")
        kind = job.get("kind", "unknown")
        label, detail, href = _job_display(job_id, job)
        actions = []
        if status in _ACTIVE_STATUSES and kind in _CANCELLABLE_KINDS:
            actions.append(f"""<form method="post" action="{url_for('cancel_job_route', job_id=job_id)}"
  class="inline-form" style="display:inline-block;"
  onsubmit="return confirm('Cancel this job? It stops after the current item finishes, not instantly.');">
  <input type="hidden" name="redirect_to" value="{url_for('jobs_index')}">
  <button class="btn btn--secondary btn--small" type="submit" style="color:#b00020;border-color:#b00020;">Cancel</button>
</form>""")
        if status not in _ACTIVE_STATUSES:
            actions.append(f"""<form method="post" action="{url_for('delete_job_route', job_id=job_id)}"
  class="inline-form" style="display:inline-block;margin-left:6px;"
  onsubmit="return confirm('Delete this job from history? This cannot be undone.');">
  <button class="btn btn--secondary btn--small" type="submit">Delete</button>
</form>""")
        actions_html = f'<div style="margin-top:8px;">{"".join(actions)}</div>' if actions else ""
        # Real <progress> bar for active jobs -- Captain roadmap item #3
        # ("unified progress-bar contract every job type implements
        # once"), same _job_progress_fraction() helper job_status_json()
        # uses, not a second implementation. Server-rendered against the
        # snapshot at page-load time; this page's own 4s full-reload (see
        # refresh_script below) is what keeps it current, matching this
        # file's stated preference for the simpler mechanism over
        # per-card JS polling for something this size.
        bar_html = ""
        if show_bar:
            frac = _job_progress_fraction(job)
            pct = round(frac * 100)
            bar_html = f"""<progress value="{frac:.4f}" max="1" style="width:100%;height:8px;margin-top:6px;"></progress>
  <div class="card__meta" style="margin-top:2px;">{pct}%</div>"""
        return f"""<div class="card">
  <div class="card__company">{_esc(kind)} &middot; {_esc(status)}</div>
  <h3 class="card__title"><a href="{href}">{_esc(label)}</a></h3>
  <div class="card__meta">{_esc(detail)}</div>
  {bar_html}
  {actions_html}
</div>"""

    active_cards = "".join(_job_link(jid, j, show_bar=True) for jid, j in active_items)
    history_cards = "".join(_job_link(jid, j, show_bar=False) for jid, j in history_items) or \
        '<div class="empty-state">No finished jobs yet.</div>'

    active_section = ""
    if any_active:
        # This section IS the multi-job mini-dashboard -- if you kick off
        # Scout, a score-batch, and a generate batch together, all three
        # show up here at once with real progress, not just as three
        # entries indistinguishable from finished history below.
        active_section = f"""<div class="detail-header" style="margin-top:0;"><h2 style="margin:0;">Active now</h2></div>
  <div class="grid">{active_cards}</div>
  <hr style="margin:24px 0;border:none;border-top:1px solid var(--hairline);">"""

    refresh_script = (
        '<script>setTimeout(function(){ window.location.reload(); }, 4000);</script>' if any_active else ""
    )
    clear_all_form = ""
    if any_finished:
        clear_all_form = f"""<form method="post" action="{url_for('clear_jobs_route')}" style="margin:8px 0 16px;"
  onsubmit="return confirm('Clear all finished job history? Jobs still running are kept. This cannot be undone.');">
  <button class="btn btn--secondary btn--small" type="submit">Clear all history</button>
</form>"""
    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Recent jobs</h1></div>
  <p class="sub">Job history -- survives a dashboard restart. A job still running when the process last stopped shows as "interrupted".</p>
  {active_section}
  <div class="detail-header" style="margin-top:0;"><h2 style="margin:0;">History</h2></div>
  {clear_all_form}
  <div class="grid">{history_cards}</div>
  <p class="sub" style="margin-top:16px;"><a class="btn btn--secondary btn--small" href="{url_for('index')}">Back to postings</a></p>
</div>{refresh_script}"""
    return _page("Recent jobs", body)


@app.route("/jobs/<job_id>/delete", methods=["POST"])
def delete_job_route(job_id):
    """Deletes one job from history. Refuses (silently, redirecting back
    unchanged) if the job is still queued/running -- an active job's
    background thread is real and will keep calling _set_job() on this
    same job_id regardless; deleting the row now would just have it
    silently reappear on the next write."""
    job = _get_job(job_id)
    if job is not None and job.get("status") not in _ACTIVE_STATUSES:
        _delete_job(job_id)
    return redirect(url_for("jobs_index"))


@app.route("/jobs/clear", methods=["POST"])
def clear_jobs_route():
    _clear_jobs()
    return redirect(url_for("jobs_index"))


def _job_progress_fraction(job: dict) -> float:
    """Single source of truth for "how far along is this job, 0..1" --
    the Captain roadmap's #3 item ("unified progress-bar contract every
    job type implements once"). Every branch below reads ONLY fields
    that kind's runner already writes for _job_display() -- no new
    per-kind state introduced for this. Used by job_status_json() (adds
    a "progress_fraction" key the generic spinner-wrap page's poll()
    reads) and jobs_index() (renders a real <progress> bar per active
    job card, not just text).

    Extension point for the token-usage/token-speed mini-dashboard
    request: once llm.py is available and LLMClient's response carries
    token counts, a parallel _job_token_stats(job) helper can read
    whatever field on_step()/on_company_done() are extended to also
    write (e.g. running tokens_generated / elapsed_seconds), following
    the same "read what the runner already writes, don't add a second
    tracking mechanism" pattern this function follows. Not built yet --
    deliberately deferred until llm.py is seen.

    Terminal statuses (done/error/cancelled/interrupted) still return a
    real number rather than 0 or None -- "done" is exactly 1.0, and a
    cancelled/interrupted job returns however far it actually got,
    which is meaningful on the jobs_index() history list (a job
    cancelled 80% through reads differently than one cancelled at the
    first item)."""
    kind = job.get("kind", "unknown")
    status = job.get("status", "unknown")

    if status == "done":
        return 1.0
    if status == "queued":
        return 0.0

    def _ratio(done: float, total: float) -> float:
        if not total:
            return 0.0
        return max(0.0, min(1.0, done / total))

    if kind == "generate":
        return _ratio(job.get("step") or 0, job.get("total_steps") or 0)

    if kind == "batch_generate":
        total = job.get("total") or 0
        if not total:
            return 0.0
        batch_index = job.get("batch_index") or 0
        step = job.get("step") or 0
        total_steps = job.get("total_steps") or 0
        inner = _ratio(step, total_steps)
        # batch_index counts the posting CURRENTLY in flight as "started,
        # not yet done" -- so completed-whole-postings is batch_index-1,
        # plus inner progress on the one in flight.
        completed_whole = max(0, batch_index - 1)
        return _ratio(completed_whole + inner, total)

    if kind == "score_batch":
        total = job.get("total") or 0
        done = (job.get("scored") or 0) + (job.get("skipped") or 0)
        return _ratio(done, total)

    if kind == "scout":
        return _ratio(job.get("companies_done") or 0, job.get("total_companies") or 0)

    if kind == "dead_link_check":
        return _ratio(job.get("checked") or 0, job.get("total") or 0)

    if kind == "scout_and_check":
        # Two sequential phases, each treated as half the bar -- an
        # approximation (scouting N companies and checking M posting
        # URLs aren't equal-cost units of work), but simple, honest
        # about being a 50/50 split, and matches this file's stated
        # preference for the smaller/simpler mechanism over a cleverer
        # weighted one for something this size.
        phase = job.get("phase", "scout")
        if phase == "scout":
            inner = _ratio(job.get("companies_done") or 0, job.get("total_companies") or 0)
            return inner * 0.5
        inner = _ratio(job.get("checked") or 0, job.get("total") or 0)
        return 0.5 + inner * 0.5

    return 0.0

def _format_token_suffix(job: dict) -> str:
    """Shared by every LLM-calling kind's detail line. Empty string
    (not None) when there's nothing to show yet, so callers can just
    `detail += _format_token_suffix(job)` unconditionally."""
    calls = job.get("llm_calls_total", 0)
    if not calls:
        return ""
    prompt = job.get("prompt_tokens_total", 0)
    completion = job.get("completion_tokens_total", 0)
    seconds = job.get("llm_seconds_total", 0.0)
    tok_s = f"{completion / seconds:.0f} tok/s" if seconds > 0 and completion else "speed n/a"
    with_usage = job.get("llm_calls_with_usage", 0)
    coverage = "" if with_usage == calls else f", {with_usage}/{calls} calls reported usage"
    return f" · {prompt + completion:,} tokens ({tok_s}{coverage})"

def _job_display(job_id: str, job: dict) -> tuple[str, str, str]:
    """Single source of truth for how a job shows up in BOTH jobs_index()
    and job_status_page() -- one implementation of "what does this job's
    title/detail/result-link look like", not two that could drift.
    Returns (label, detail, link_url). Every field referenced here is one
    a job runner ALREADY writes (_run_generation/_run_batch_generation/
    _run_score_batch/_run_scout_job/_run_dead_link_check_job) -- no new
    job-dict shape introduced for this."""
    kind = job.get("kind", "unknown")
    status = job.get("status", "unknown")

    if kind == "generate":
        label = f"{job.get('company_name') or '?'} \u2014 {job.get('job_title') or '?'}"
        if status == "done":
            detail = "Done"
            href = url_for("posting_detail", posting_id=job.get("posting_id")) if job.get("posting_id") else url_for("job_status_page", job_id=job_id)
        elif status == "cancelled":
            detail = "Cancelled \u2014 no draft was saved"
            href = url_for("posting_detail", posting_id=job.get("posting_id")) if job.get("posting_id") else url_for("job_status_page", job_id=job_id)
        elif status == "interrupted":
            detail = "Interrupted by a dashboard restart \u2014 no draft was saved"
            href = url_for("posting_detail", posting_id=job.get("posting_id")) if job.get("posting_id") else url_for("job_status_page", job_id=job_id)
        elif status == "error":
            detail = f"Failed: {job.get('error', '')}"
            href = url_for("job_status_page", job_id=job_id)
        else:
            total_steps = job.get("total_steps") or 0
            step = job.get("step") or 0
            detail = f"{job.get('current') or 'starting…'}" + (f" (step {step}/{total_steps})" if total_steps else "")
            href = url_for("job_status_page", job_id=job_id)
        detail += _format_token_suffix(job)
        return label, detail, href

    if kind == "batch_generate":
        total = job.get("total") or 0
        label = f"Batch generate \u2014 {total} posting(s)"
        if status == "done":
            detail = f"{job.get('succeeded', 0)} succeeded, {job.get('failed', 0)} failed"
        elif status == "cancelled":
            done_count = len(job.get("results") or [])
            detail = f"Cancelled after {done_count} of {total} \u2014 {job.get('succeeded', 0)} succeeded, {job.get('failed', 0)} failed"
        elif status == "interrupted":
            results = job.get("results") or []
            succ = sum(1 for r in results if r.get("status") == "done")
            fail = sum(1 for r in results if r.get("status") == "error")
            detail = f"Interrupted by a dashboard restart after {len(results)} of {total} \u2014 {succ} succeeded, {fail} failed"
        elif status == "error":
            detail = f"Failed: {job.get('error', '')}"
        else:
            idx = job.get("batch_index") or 0
            cur = job.get("current_company") or ""
            title = job.get("current_title") or ""
            step = job.get("step") or 0
            total_steps = job.get("total_steps") or 0
            detail = f"Posting {idx} of {total}"
            if cur:
                detail += f" \u2014 {cur} \u2014 {title}"
            if total_steps:
                detail += f" (step {step}/{total_steps})"
        detail += _format_token_suffix(job)
        return label, detail, url_for("job_status_page", job_id=job_id)

    if kind == "score_batch":
        total = job.get("total") or 0
        label = f"Score batch \u2014 {total} filtered posting(s)"
        detail = f"{job.get('scored', 0)} scored, {job.get('skipped', 0)} skipped, of {total}"
        if status == "cancelled":
            detail = "Cancelled \u2014 " + detail
        elif status == "interrupted":
            detail = "Interrupted by a dashboard restart \u2014 " + detail
        elif status == "error":
            detail = f"Failed: {job.get('error', '')}"
        elif status in ("queued", "running") and job.get("current"):
            detail += f" \u2014 currently: {job['current']}"
        detail += _format_token_suffix(job)
        return label, detail, url_for("job_status_page", job_id=job_id)

    if kind == "scout":
        label = "Scout run"
        if status == "done":
            detail = f"{job.get('companies_checked', 0)} companies checked, {job.get('new_postings', 0)} new"
            if job.get("error_count"):
                detail += f", {job['error_count']} error(s)"
        elif status == "cancelled":
            detail = (f"Cancelled after {job.get('companies_checked', 0)} of {job.get('total_companies', 0)} "
                      f"companies \u2014 {job.get('new_postings', 0)} new so far")
            if job.get("error_count"):
                detail += f", {job['error_count']} error(s)"
        elif status == "interrupted":
            detail = (f"Interrupted by a dashboard restart after {job.get('companies_done', 0)} of "
                      f"{job.get('total_companies', 0)} companies checked")
        elif status == "error":
            detail = f"Failed: {job.get('error', '')}"
        else:
            total_companies = job.get("total_companies") or 0
            done = job.get("companies_done") or 0
            detail = f"{done} of {total_companies} companies checked" if total_companies else "Checking company career pages…"
            if job.get("current_company"):
                detail += f" \u2014 last: {job['current_company']}"
        return label, detail, url_for("job_status_page", job_id=job_id)

    if kind == "dead_link_check":
        label = "Dead link check"
        if status == "done":
            detail = f"{len(job.get('dead', []))} dead, {len(job.get('uncertain', []))} inconclusive"
            return label, detail, url_for("dead_links_results", job_id=job_id)
        if status == "cancelled":
            detail = (f"Cancelled after {job.get('checked', 0)} of {job.get('total', 0)} checked \u2014 "
                      f"{len(job.get('dead', []))} dead, {len(job.get('uncertain', []))} inconclusive so far")
            return label, detail, url_for("dead_links_results", job_id=job_id)
        if status == "interrupted":
            detail = (f"Interrupted by a dashboard restart after {job.get('checked', 0)} of {job.get('total', 0)} checked \u2014 "
                      f"{len(job.get('dead', []))} dead, {len(job.get('uncertain', []))} inconclusive so far")
            return label, detail, url_for("dead_links_results", job_id=job_id)
        if status == "error":
            detail = f"Failed: {job.get('error', '')}"
        else:
            detail = f"{job.get('checked', 0)} of {job.get('total', 0)} checked"
            if job.get("current"):
                detail += f" \u2014 currently: {job['current']}"
        return label, detail, url_for("job_status_page", job_id=job_id)

    if kind == "scout_and_check":
        label = "Scout + dead-link check"
        phase = job.get("phase", "scout")
        if status == "done":
            detail = (f"{job.get('companies_checked', 0)} companies checked, {job.get('new_postings', 0)} new "
                      f"\u2014 {len(job.get('dead', []))} dead link(s), {len(job.get('uncertain', []))} inconclusive")
            if job.get("error_count"):
                detail += f", {job['error_count']} scout error(s)"
            return label, detail, url_for("dead_links_results", job_id=job_id)
        if status == "cancelled":
            if phase == "scout":
                detail = (f"Cancelled during scouting, after {job.get('companies_done', 0)} of "
                          f"{job.get('total_companies', 0)} companies \u2014 dead-link check not started")
            else:
                detail = (f"Scout finished ({job.get('companies_checked', 0)} companies, "
                          f"{job.get('new_postings', 0)} new); cancelled during dead-link check after "
                          f"{job.get('checked', 0)} of {job.get('total', 0)} checked \u2014 "
                          f"{len(job.get('dead', []))} dead, {len(job.get('uncertain', []))} inconclusive so far")
            return label, detail, url_for("dead_links_results", job_id=job_id)
        if status == "interrupted":
            if phase == "scout":
                detail = (f"Interrupted by a dashboard restart during scouting, after "
                          f"{job.get('companies_done', 0)} of {job.get('total_companies', 0)} companies \u2014 "
                          f"dead-link check not started")
            else:
                detail = (f"Interrupted by a dashboard restart during dead-link check, after "
                          f"{job.get('checked', 0)} of {job.get('total', 0)} checked \u2014 "
                          f"{len(job.get('dead', []))} dead, {len(job.get('uncertain', []))} inconclusive so far")
            return label, detail, url_for("dead_links_results", job_id=job_id)
        if status == "error":
            detail = f"Failed during {'scouting' if phase == 'scout' else 'dead-link check'}: {job.get('error', '')}"
        elif phase == "scout":
            total_companies = job.get("total_companies") or 0
            done = job.get("companies_done") or 0
            detail = f"Scouting: {done} of {total_companies} companies checked" if total_companies else "Scouting: checking company career pages\u2026"
            if job.get("current_company"):
                detail += f" \u2014 last: {job['current_company']}"
        else:
            detail = f"Checking links: {job.get('checked', 0)} of {job.get('total', 0)} checked"
            if job.get("current"):
                detail += f" \u2014 currently: {job['current']}"
        return label, detail, url_for("job_status_page", job_id=job_id)

    return kind, status, url_for("job_status_page", job_id=job_id)


def _run_generation(
    job_id: str,
    posting_id: int,
    company_name: str,
    job_title: str,
    job_description: str,
    revision_rounds: int,
    think: bool,
    stability: str,
) -> None:
    """Runs in a background thread, started by POST /postings/<id>/generate.
    Opens its own DB connection rather than sharing the request's --
    libsql connections aren't guaranteed thread-safe to share across
    threads, and this thread outlives the request that started it.

    Progress: total_steps is computed deterministically up front (10
    units of work per round -- see run_revision_loop()'s on_step
    docstring -- times revision_rounds+1 rounds), then on_step() ticks
    `step` up by one and records a human label in `current` as each unit
    finishes. This is a REAL count against real completed work, not a
    time-based animation -- same "actual per-unit count, not a
    fabricated bar" approach _run_score_batch()/run_scout()'s progress
    already use in this file.
    """
    total_steps = 10 * (revision_rounds + 1)
    step_state = {"n": 0}
    job_start_time = time.time()

    def on_step(label: str) -> None:
        step_state["n"] += 1
        _set_job(job_id, step=step_state["n"], total_steps=total_steps, current=label)
        if (_get_job(job_id) or {}).get("cancel_requested"):
            raise _JobCancelled()

    _set_job(
        job_id, status="running", posting_id=posting_id, kind="generate",
        company_name=company_name, job_title=job_title,
        step=0, total_steps=total_steps, current="starting…",
    )
    try:
        # _run_generation (job_id is already that function's own param):
        client = LLMClient(usage_callback=_make_usage_callback(job_id))
        result = run_revision_loop(
            client,
            company_name=company_name,
            job_title=job_title,
            job_description=job_description,
            revision_rounds=revision_rounds,
            think=think,
            stability=stability,
            on_step=on_step,
        )
        conn = get_connection()
        init_schema(conn)
        draft_id = drafts_db.save_draft(conn, posting_id, result)
        _set_job(job_id, status="done", draft_id=draft_id)
        _log_token_usage("generate", job_id, duration_seconds=time.time() - job_start_time)
    except _JobCancelled:
        logger.info("generation for posting %s cancelled by user (job %s)", posting_id, job_id)
        _set_job(job_id, status="cancelled")
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the polling page, don't just log it
        logger.exception("generation failed for posting %s", posting_id)
        _set_job(job_id, status="error", error=str(exc))


def _run_batch_generation(
    job_id: str,
    items: list[dict],
    revision_rounds: int,
    think: bool,
    stability: str,
) -> None:
    """Runs in a background thread, started by POST
    /postings/batch-generate/start. `items` is a list of
    {posting_id, company, title, description} dicts, already filtered to
    only postings that have a stored description (batch has no
    per-posting paste step) -- see batch_generate_confirm()/
    batch_generate_start().

    SEQUENTIAL BY DESIGN, confirmed with the user, not a shortcut: one
    posting is generated at a time, not in parallel, specifically to
    protect the local Ollama model's KV cache on this machine. Parallel
    execution (a more powerful machine, or routing to a frontier API) is
    an explicitly deferred future option -- not built here.

    Does NOT call _run_generation() -- that function writes status/kind/
    step/total_steps under whatever job_id it's given, and reusing it
    here would collide with this function's own writes to the SAME
    job_id across multiple postings. The per-posting step-counting logic
    (10 units of work per round, matching run_revision_loop()'s on_step
    contract) is duplicated here rather than factored into a shared
    helper -- a small amount of duplication over a shared helper for
    something this size, consistent with this project's stated
    preference.

    Per-posting failure handling: confirmed with the user, not assumed.
    A single posting's generation error is caught, recorded in
    `results` with status='error', and the loop CONTINUES to the next
    posting -- one bad posting never loses progress already made on the
    others. All results (done and error) are visible together once the
    whole batch finishes, nothing buried in only a log line.

    Progress fields written to the job dict:
    - batch_index / total: which posting (1-based) is current, out of
      how many
    - current_company / current_title: which posting is running now
    - step / total_steps / current: the SAME per-posting step contract
      _run_generation() uses, so the batch status page can show a real
      nested progress bar for the posting in flight, not just the outer
      count
    - results: grows by one entry after each posting finishes (done or
      error), read by job_status_page()'s batch_generate branch to show
      a running list, not just a final summary
    """
    total = len(items)
    job_start_time = time.time()
    _set_job(
        job_id, status="running", kind="batch_generate",
        posting_ids=[it["posting_id"] for it in items],
        total=total, batch_index=0, current_company="", current_title="",
        step=0, total_steps=0, current="", results=[],
    )
    results: list[dict] = []
    for idx, item in enumerate(items, start=1):
        if (_get_job(job_id) or {}).get("cancel_requested"):
            break
        posting_id = item["posting_id"]
        company_name = item["company"]
        job_title = item["title"]
        job_description = item["description"]

        total_steps = 10 * (revision_rounds + 1)
        step_state = {"n": 0}

        def on_step(label: str, _step_state=step_state, _total_steps=total_steps) -> None:
            _step_state["n"] += 1
            _set_job(job_id, step=_step_state["n"], total_steps=_total_steps, current=label)

        _set_job(
            job_id, batch_index=idx, current_company=company_name, current_title=job_title,
            step=0, total_steps=total_steps, current="starting…",
        )
        conn = get_connection()
        init_schema(conn)
        # Regenerate-while-editing handling (Writer subsystem #4), same
        # as the single-posting generate() route -- batch generation can
        # also regenerate a posting that already has both a draft and an
        # in-progress hand edit (see batch_generate_confirm()'s own
        # docstring: "batch generation adds a new draft row, same as
        # clicking Regenerate today"), so it needs the identical
        # archive-before-overwrite guard, not just the single-posting path.
        drafts_db.archive_final_edit(conn, posting_id)
        try:
            # _run_batch_generation -- INSIDE the per-posting loop, same job_id
            # (the whole batch shares one job_id, so this correctly accumulates
            # across every posting in the batch, not just the last one):
            client = LLMClient(usage_callback=_make_usage_callback(job_id))
            result = run_revision_loop(
                client,
                company_name=company_name,
                job_title=job_title,
                job_description=job_description,
                revision_rounds=revision_rounds,
                think=think,
                stability=stability,
                on_step=on_step,
            )
            draft_id = drafts_db.save_draft(conn, posting_id, result)
            results.append({
                "posting_id": posting_id, "company": company_name, "title": job_title,
                "status": "done", "draft_id": draft_id,
            })
        except Exception as exc:  # noqa: BLE001 -- per-posting failure, batch continues
            logger.exception("batch generation failed for posting %s (job %s)", posting_id, job_id)
            results.append({
                "posting_id": posting_id, "company": company_name, "title": job_title,
                "status": "error", "error": str(exc),
            })
        _set_job(job_id, results=list(results))

    succeeded = sum(1 for r in results if r["status"] == "done")
    failed = sum(1 for r in results if r["status"] == "error")
    was_cancelled = (_get_job(job_id) or {}).get("cancel_requested", False)
    _set_job(
        job_id, status=("cancelled" if was_cancelled else "done"),
        results=results, succeeded=succeeded, failed=failed,
    )
    _log_token_usage("batch_generate", job_id, duration_seconds=time.time() - job_start_time)


def _run_score_batch(
    job_id: str,
    posting_rows: list[tuple],
    rescore: bool,
    think: bool,
) -> None:
    """Runs in a background thread, started by POST /postings/score-batch.
    posting_rows is EXACTLY the filtered set the postings-index rendered
    at click time (id, company, title, location, status, description) --
    the caller already ran it through the same keyword_filter_match()
    logic index() uses, this function does no filtering of its own.

    Mirrors cli.py's cmd_score_postings loop deliberately -- same skip
    condition (no description), same UPDATE statement (status only
    flips 'new' -> 'scored', an already-'scored' or other-status row
    keeps its status), same per-posting commit, same "still counts as
    scored" treatment of an unparseable result (score/rationale written
    as NULL rather than silently dropped) -- this is the second caller
    of that write pattern, not a divergent one.

    rescore: if False (the default, matching cli.py's own default),
    postings whose status isn't 'new' are skipped without an LLM call --
    same semantics as omitting --rescore on the CLI. If True, every
    filtered posting with a description gets (re-)scored regardless of
    current status.

    Opens its own DB connection and its own LLMClient, same reasoning as
    _run_generation: this thread outlives the request that started it.
    """
    total = len(posting_rows)
    job_start_time = time.time()
    _set_job(job_id, status="running", kind="score_batch", total=total, scored=0, skipped=0, current="")
    try:
        criteria = load_search_criteria()
        # _run_score_batch:
        client = LLMClient(usage_callback=_make_usage_callback(job_id))
        conn = get_connection()
        init_schema(conn)

        scored = 0
        skipped = 0
        for posting_id, company, title, location, status, description in posting_rows:
            if (_get_job(job_id) or {}).get("cancel_requested"):
                break
            _set_job(job_id, current=f"{company} -- {title}")
            if not description:
                skipped += 1
                _set_job(job_id, skipped=skipped)
                continue
            if not rescore and status != "new":
                skipped += 1
                _set_job(job_id, skipped=skipped)
                continue
            result = score_posting(client, company, title, location, description, criteria, think=think)
            conn.execute(
                "UPDATE postings SET score = ?, score_rationale = ?, "
                "status = CASE WHEN status = 'new' THEN 'scored' ELSE status END WHERE id = ?",
                (result.score, result.rationale, posting_id),
            )
            conn.commit()
            scored += 1
            _set_job(job_id, scored=scored)

        was_cancelled = (_get_job(job_id) or {}).get("cancel_requested", False)
        _set_job(job_id, status=("cancelled" if was_cancelled else "done"), scored=scored, skipped=skipped, total=total)
        _log_token_usage("score_batch", job_id, duration_seconds=time.time() - job_start_time)
    except Exception as exc:  # noqa: BLE001
        logger.exception("score batch job %s failed", job_id)
        _set_job(job_id, status="error", error=str(exc))


def _run_scout_job(job_id: str) -> None:
    """Runs in a background thread, started by POST /scout/run. Calls
    run_scout() directly -- the same function cli.py's cmd_run_scout
    calls -- and logs to run_log via cli.py's own _log_run(), reused
    rather than duplicated (imported, not copy-pasted).

    GAP CLOSED (was previously stated rather than papered over): earlier
    sessions couldn't wire real per-company progress because run_scout()
    itself gave nothing to hook into -- it built its whole results list
    in-memory and only returned once, after every company was checked.
    Now that detector.py has been seen, run_scout() takes an optional
    `on_company_done` callback, called once per company right after that
    company's ScoutResult exists. This function passes a small closure
    that updates the job dict (via the same _set_job() every other job
    kind already uses) with the running total-so-far, same pattern
    _run_score_batch() already uses per-posting -- one implementation
    style, not a divergent one. total_companies is set up front from
    load_companies() so the status line can show "N of M", not just "N
    so far" with no denominator.
    """
    _set_job(job_id, status="running", kind="scout", companies_done=0,
              total_companies=len(load_companies()), current_company="")

    def _on_company_done(result) -> None:
        job = _get_job(job_id) or {}
        _set_job(
            job_id,
            companies_done=job.get("companies_done", 0) + 1,
            current_company=result.company_name,
        )

    def _should_stop() -> bool:
        return (_get_job(job_id) or {}).get("cancel_requested", False)

    try:
        results = run_scout(on_company_done=_on_company_done, should_stop=_should_stop)
        total_new = sum(r.new_postings for r in results)
        errors = [r for r in results if r.strategy == "error"]

        conn = get_connection()
        init_schema(conn)
        log_status = "ok" if not errors else "partial"
        detail = json.dumps({
            "companies_checked": len(results),
            "new_postings": total_new,
            "errors": [{"company": r.company_name, "error": r.error} for r in errors],
        })
        _log_run(conn, log_status, detail)

        was_cancelled = (_get_job(job_id) or {}).get("cancel_requested", False)
        _set_job(
            job_id, status=("cancelled" if was_cancelled else "done"),
            companies_checked=len(results), new_postings=total_new, error_count=len(errors),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("scout job %s failed", job_id)
        _set_job(job_id, status="error", error=str(exc))


def _run_dead_link_check_job(job_id: str, posting_rows: list[tuple]) -> None:
    """Runs in a background thread, started by POST /postings/check-dead-links.
    posting_rows is (id, company, title, url) for every non-stale posting in
    the DB at click time -- a real per-posting HTTP check, not a heuristic,
    answering exactly the question a person clicking 'original posting' and
    getting a 404 already answers by hand, just at scale.

    Results (dead + uncertain lists) are held in the job dict and read by
    dead_links_results() once the job finishes -- POST /postings/mark-stale
    is the only route that actually writes status='stale', and only for
    posting_ids a person explicitly checked and submitted.

    Uses one shared RateLimiter across the whole sweep so per-domain
    politeness (the same one Scout's own fetches respect) applies across
    hundreds of postings hitting a handful of ATS domains, not a fresh
    limiter (and fresh cooldown state) per posting.

    `uncertain` is now a full list (id/company/title/url/detail), not
    just a count -- added after the first real run surfaced 153/947
    (16%) inconclusive with no way to see WHICH postings or WHY, a
    number too large to leave unexamined. Kept read-only on the results
    page (no checkbox, no mark-stale action) since "inconclusive" is
    explicitly not a dead-link claim -- see check_url_alive()'s and
    _check_workday_url_alive()'s own docstrings for why guessing here
    would risk false positives the confident-dead list is built to
    avoid.
    """
    total = len(posting_rows)
    _set_job(job_id, status="running", kind="dead_link_check", total=total,
              checked=0, dead=[], uncertain=[], current="")
    limiter = RateLimiter()
    try:
        dead: list[dict] = []
        uncertain: list[dict] = []
        for i, (posting_id, company, title, url) in enumerate(posting_rows, start=1):
            if (_get_job(job_id) or {}).get("cancel_requested"):
                break
            _set_job(job_id, current=f"{company} -- {title}")
            is_alive, detail = check_url_alive(url, limiter)
            entry = {"id": posting_id, "company": company, "title": title, "url": url, "detail": detail}
            if is_alive is False:
                dead.append(entry)
            elif is_alive is None:
                uncertain.append(entry)
            _set_job(job_id, checked=i, dead=dead, uncertain=uncertain)

        was_cancelled = (_get_job(job_id) or {}).get("cancel_requested", False)
        final_checked = (_get_job(job_id) or {}).get("checked", 0)
        _set_job(job_id, status=("cancelled" if was_cancelled else "done"), checked=final_checked, dead=dead, uncertain=uncertain)
    except Exception as exc:  # noqa: BLE001
        logger.exception("dead link check job %s failed", job_id)
        _set_job(job_id, status="error", error=str(exc))


def _run_scout_and_check_job(job_id: str) -> None:
    """Runs in a background thread, started by POST /scout-and-check/run.
    Captain roadmap item #4 ("combine Run Scout and check-for-dead-links
    into one job"), built per direct request: there's no point trying to
    apply to postings that are no longer there, so a single run now does
    both -- Scout first (find new postings, mark stale anything a
    successfully-scraped company page no longer lists), then a full
    dead-link sweep (catch postings whose company page still 200s but
    the individual posting URL is now 404/410/gone).

    Deliberately duplicates _run_scout_job()'s and
    _run_dead_link_check_job()'s loop bodies rather than refactoring them
    to share code -- both are already confirmed live from earlier this
    session; this is new code running alongside them, not an edit to a
    path that already works.

    The dead-link half's human review gate is UNCHANGED: this job only
    ever populates job["dead"]/job["uncertain"], same as
    _run_dead_link_check_job(). Nothing here calls mark_stale_route()'s
    UPDATE directly -- see that route's docstring for why a detected dead
    link is a candidate, not a write, until a person reviews and submits
    dead_links_results()'s form. Explicit choice, kept from the standalone
    dead-link-check feature: the first real sweep came back 16%
    inconclusive, and auto-marking stale without a look would risk
    quietly hiding postings that are still live.

    job["phase"] is "scout" during the first half, "dead_link_check"
    during the second -- read by _job_display()/_job_progress_fraction()
    to know which set of fields (companies_done/total_companies vs.
    checked/total) currently means something. Cancel is checked at both
    phase boundaries (once per company; once per posting URL), same
    cancel_requested field every other job kind uses.
    """
    _set_job(job_id, status="running", kind="scout_and_check", phase="scout",
              companies_done=0, total_companies=len(load_companies()), current_company="")

    def _on_company_done(result) -> None:
        job = _get_job(job_id) or {}
        _set_job(
            job_id,
            companies_done=job.get("companies_done", 0) + 1,
            current_company=result.company_name,
        )

    def _should_stop() -> bool:
        return (_get_job(job_id) or {}).get("cancel_requested", False)

    try:
        # --- Phase 1: Scout ---------------------------------------------
        results = run_scout(on_company_done=_on_company_done, should_stop=_should_stop)
        total_new = sum(r.new_postings for r in results)
        errors = [r for r in results if r.strategy == "error"]

        conn = get_connection()
        init_schema(conn)
        log_status = "ok" if not errors else "partial"
        detail = json.dumps({
            "companies_checked": len(results),
            "new_postings": total_new,
            "errors": [{"company": r.company_name, "error": r.error} for r in errors],
        })
        _log_run(conn, log_status, detail)

        _set_job(
            job_id,
            companies_checked=len(results), new_postings=total_new, error_count=len(errors),
        )

        scout_cancelled = (_get_job(job_id) or {}).get("cancel_requested", False)
        if scout_cancelled:
            _set_job(job_id, status="cancelled")
            return

        # --- Phase 2: dead-link check, over every non-stale posting ------
        # (freshly re-queried -- Phase 1 may have just inserted new rows
        # and marked others stale, so this must NOT reuse a pre-scout
        # snapshot of the postings table.)
        rows = conn.execute(
            """SELECT postings.id, companies.name, postings.title, postings.url
               FROM postings JOIN companies ON postings.company_id = companies.id
               WHERE postings.status != 'stale'
               ORDER BY companies.name, postings.title"""
        ).fetchall()
        total = len(rows)
        _set_job(job_id, phase="dead_link_check", total=total, checked=0, dead=[], uncertain=[], current="")

        limiter = RateLimiter()
        dead: list[dict] = []
        uncertain: list[dict] = []
        for i, (posting_id, company, title, url) in enumerate(rows, start=1):
            if (_get_job(job_id) or {}).get("cancel_requested"):
                break
            _set_job(job_id, current=f"{company} \u2014 {title}")
            is_alive, link_detail = check_url_alive(url, limiter)
            entry = {"id": posting_id, "company": company, "title": title, "url": url, "detail": link_detail}
            if is_alive is False:
                dead.append(entry)
            elif is_alive is None:
                uncertain.append(entry)
            _set_job(job_id, checked=i, dead=dead, uncertain=uncertain)

        was_cancelled = (_get_job(job_id) or {}).get("cancel_requested", False)
        final_checked = (_get_job(job_id) or {}).get("checked", 0)
        _set_job(job_id, status=("cancelled" if was_cancelled else "done"), checked=final_checked, dead=dead, uncertain=uncertain)
    except Exception as exc:  # noqa: BLE001
        logger.exception("scout_and_check job %s failed", job_id)
        _set_job(job_id, status="error", error=str(exc))


# ---------------------------------------------------------------------------
# Small DB helpers local to the dashboard -- one posting lookup shape
# every route below needs, kept here rather than in db.py since it's a
# dashboard-specific join (postings + companies), not a schema concern.
# ---------------------------------------------------------------------------


def _get_posting(conn, posting_id: int) -> dict | None:
    row = conn.execute(
        """SELECT postings.id, companies.name, postings.title, postings.location,
                  postings.url, postings.apply_url, postings.description, postings.status
           FROM postings JOIN companies ON postings.company_id = companies.id
           WHERE postings.id = ?""",
        (posting_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("id", "company", "title", "location", "url", "apply_url", "description", "status")
    return dict(zip(keys, row))


# ---------------------------------------------------------------------------
# Page shell + shared styling. Reuses report.py's design tokens (_STYLE)
# so the dashboard and the static single-posting report read as one
# product, not two -- only dashboard-specific chrome (cards, badges,
# forms, the polling spinner) is defined here.
# ---------------------------------------------------------------------------

_DASHBOARD_STYLE = """
.topbar {
  background: var(--ink); color: #F6F7F5; padding: 18px 24px;
}
.topbar a { color: #F6F7F5; text-decoration: none; font-weight: 650; font-size: 15px; }
.topbar__wrap { max-width: 1040px; margin: 0 auto; }
.dash-wrap { max-width: 1040px; margin: 0 auto; padding: 28px 24px 96px; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.card {
  background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px;
  padding: 18px 20px; display: flex; flex-direction: column; gap: 6px;
}
.card__company { font-size: 12px; font-family: var(--mono); color: var(--accent); text-transform: uppercase; letter-spacing: 0.05em; }
.card__title { font-size: 16px; font-weight: 650; margin: 0; }
.card__meta { font-size: 12.5px; color: var(--ink-faint); }
.card__footer { margin-top: 10px; display: flex; align-items: center; justify-content: space-between; }
.badge {
  font-family: var(--mono); font-size: 12px; padding: 3px 9px; border-radius: 3px; font-weight: 600;
}
.badge--good { color: var(--good); background: var(--good-bg); }
.badge--mid { color: var(--mid); background: var(--mid-bg); }
.badge--low { color: var(--low); background: var(--low-bg); }
.badge--unknown, .badge--none { color: var(--unknown); background: var(--unknown-bg); }
.card__link { font-size: 13px; font-weight: 600; color: var(--accent); text-decoration: none; }
.card__link:hover { text-decoration: underline; }

.detail-header { margin-bottom: 20px; display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.detail-header h1 { margin: 0 0 4px; font-size: 24px; }
.detail-header .sub { color: var(--ink-soft); font-size: 14.5px; width: 100%; }
.inline-form { display: inline-block; }

.score-batch-bar { background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px;
  padding: 12px 16px; margin-bottom: 20px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.score-batch-bar .checkbox-field { display: flex; align-items: center; gap: 6px; }
.score-batch-bar .checkbox-field label { margin: 0; }

.jd-box { width: 100%; min-height: 240px; font-family: var(--mono); font-size: 13px;
  border: 1px solid var(--hairline); border-radius: 4px; padding: 12px; resize: vertical; }

.editor-panel { background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px;
  padding: 14px 18px; }
.editor-panel[open] { padding-bottom: 20px; }
.editor-panel > summary { list-style: none; cursor: pointer; font-weight: 650; font-size: 14.5px;
  color: var(--ink); display: flex; align-items: center; gap: 8px; }
.editor-panel > summary::-webkit-details-marker { display: none; }
.editor-panel > summary::before {
  content: "\25B8"; color: var(--ink-faint); display: inline-block; transition: transform 0.15s;
}
.editor-panel[open] > summary::before { transform: rotate(90deg); }
.editor-panel .edited-badge { font-weight: 500; color: var(--ink-faint); font-size: 12.5px; }
.editor-field { margin-top: 14px; }
.editor-field label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: var(--ink); }
.editor-box { width: 100%; font-family: var(--mono); font-size: 13px;
  border: 1px solid var(--hairline); border-radius: 4px; padding: 10px 12px; resize: vertical; }
.history-entry { border: 1px solid var(--hairline); border-radius: 4px; margin-top: 10px; padding: 10px 14px; }
.history-entry > summary { cursor: pointer; font-size: 13px; color: var(--ink-faint); list-style: none; }
.history-entry > summary::-webkit-details-marker { display: none; }
.history-entry[open] { padding-bottom: 14px; }
.history-entry__body { margin-top: 10px; }
.history-entry__field-label { font-weight: 600; font-size: 12.5px; margin: 10px 0 4px; }
.history-entry__text { white-space: pre-wrap; font-family: var(--mono); font-size: 13px; margin: 0; }
#edit_summary, #edit_cover { min-height: 100px; }
#edit_bullets { min-height: 160px; }

.form-row { margin: 14px 0; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
label { font-size: 13.5px; color: var(--ink-soft); }
input[type=number] { width: 64px; font-family: var(--mono); padding: 4px 6px; border: 1px solid var(--hairline); border-radius: 3px; }

.btn, .btn:link, .btn:visited {
  font-family: var(--sans); font-size: 14px; font-weight: 650; padding: 10px 18px;
  border-radius: 4px; border: none; cursor: pointer; background: var(--accent); color: #fff;
  text-decoration: none; display: inline-block;
}
.btn:hover { opacity: 0.92; }
.btn--secondary, .btn--secondary:link, .btn--secondary:visited {
  background: var(--panel); color: var(--ink); border: 1px solid var(--hairline);
}
.card__link, .card__link:link, .card__link:visited { text-decoration: none; }
.btn-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }

.result-summary { display: flex; align-items: center; gap: 20px; background: var(--panel);
  border: 1px solid var(--hairline); border-radius: 4px; padding: 20px; margin: 20px 0; }
.result-summary .dial { min-width: 90px; }

.spinner-wrap { text-align: center; padding: 80px 20px; }
.spinner {
  width: 36px; height: 36px; margin: 0 auto 20px; border-radius: 50%;
  border: 3px solid var(--hairline); border-top-color: var(--accent);
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.empty-state { color: var(--ink-faint); text-align: center; padding: 60px 20px; }

.filter-bar { background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px;
  padding: 16px 18px; margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 14px 20px; align-items: flex-end; }
.filter-bar .field { display: flex; flex-direction: column; gap: 4px; }
.filter-bar input[type=text], .filter-bar input[type=date], .filter-bar select, .filter-bar input[type=number] {
  font-family: var(--sans); font-size: 13.5px; padding: 6px 8px; border: 1px solid var(--hairline);
  border-radius: 3px; width: auto; }
.filter-bar .checkbox-field { display: flex; align-items: center; gap: 6px; }
.filter-bar .checkbox-field label { margin: 0; }
.filter-bar .actions { display: flex; gap: 8px; margin-left: auto; }
.btn--small, .btn--small:link, .btn--small:visited { padding: 6px 14px; font-size: 13px; }

.pagination { display: flex; justify-content: center; gap: 6px; margin-top: 28px; }
.pagination a, .pagination span { font-family: var(--mono); font-size: 13px; padding: 6px 12px;
  border: 1px solid var(--hairline); border-radius: 3px; text-decoration: none; color: var(--ink); }
.pagination .current { background: var(--accent); color: #fff; border-color: var(--accent); }

textarea.manual-jd { width: 100%; min-height: 180px; font-family: var(--mono); font-size: 13px;
  border: 1px solid var(--hairline); border-radius: 4px; padding: 12px; resize: vertical; }
input[type=text].wide { width: 100%; font-family: var(--sans); font-size: 14px; padding: 8px 10px;
  border: 1px solid var(--hairline); border-radius: 4px; }

/* Roomy tables (added for /tokens' per-run view, 2026-08-23) -- prior to
   this, this file had no table styling at all, so any <table> fell back
   to cramped browser defaults with no padding or row separation. */
.dash-wrap--wide { max-width: 1320px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 20px; }
th, td { padding: 12px 16px; text-align: left; vertical-align: top; font-size: 13.5px; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-faint);
  border-bottom: 2px solid var(--hairline); }
td { border-bottom: 1px solid var(--hairline); }
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-family: var(--mono); }
.token-summary { display: flex; gap: 28px; flex-wrap: wrap; background: var(--panel);
  border: 1px solid var(--hairline); border-radius: 4px; padding: 16px 20px; margin-bottom: 20px; }
.token-summary .stat { display: flex; flex-direction: column; gap: 2px; }
.token-summary .stat .n { font-family: var(--mono); font-size: 20px; font-weight: 650; }
.token-summary .stat .label { font-size: 12px; color: var(--ink-faint); }
.calc-inputs { display: flex; gap: 20px; flex-wrap: wrap; margin: 12px 0 18px; }
.calc-inputs label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px;
  color: var(--ink-faint); font-weight: 500; }
.calc-inputs input[type="number"] { font-family: var(--mono); font-size: 14px; padding: 6px 8px;
  border: 1px solid var(--hairline); border-radius: 4px; width: 160px; }
.calc-output-size { margin-bottom: 14px; }
.calc-presets { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.calc-preset { font-size: 12.5px; padding: 5px 10px; border: 1px solid var(--hairline);
  border-radius: 999px; background: var(--panel); cursor: pointer; }
.calc-preset:hover { border-color: var(--accent); }
.calc-output-size input[type="range"] { width: 100%; max-width: 480px; display: block; margin: 6px 0; }
.calc-output-readout { font-size: 13px; color: var(--ink-faint); }
.calc-sort-toggle { display: flex; gap: 8px; margin: 4px 0 12px; }
.calc-sort-btn { font-size: 12.5px; padding: 5px 12px; border: 1px solid var(--hairline);
  border-radius: 4px; background: var(--panel); cursor: pointer; }
.calc-sort-btn--active { background: var(--accent); color: #fff; border-color: var(--accent); }
.calc-row { cursor: pointer; }
.calc-row:hover { background: var(--panel); }
.calc-row--active { background: var(--accent-faint, #eef); font-weight: 600; }
.calc-provider { color: var(--ink-faint); font-weight: 400; font-size: 12px; }
.run-tok-link { color: inherit; text-decoration: underline dotted; cursor: pointer; }
.run-tok-link:hover { color: var(--accent); }
td.dyn-cost, th.dyn-cost { border-left: 2px solid var(--accent); }
.result-links { font-size: 13px; }
.result-links a { color: var(--accent); text-decoration: none; }
.result-links a:hover { text-decoration: underline; }
.result-links details summary { cursor: pointer; color: var(--accent); font-weight: 600; }
"""


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} — BioHunter</title>
<style>{_REPORT_STYLE}{_DASHBOARD_STYLE}</style>
</head>
<body>
<div class="topbar"><div class="topbar__wrap">
  <a href="{url_for('index')}">BioHunter</a>
  <span id="job-indicator" style="float:right;font-size:13px;color:var(--ink-faint);"></span>
  <a id="notif-enable" href="#" style="float:right;font-weight:500;font-size:13px;margin-right:14px;display:none;">Enable notifications</a>
  <a href="{url_for('settings_page')}" style="float:right;font-weight:500;font-size:13.5px;margin-right:14px;">Settings</a>
  <a href="{url_for('tokens_dashboard')}" style="float:right;font-weight:500;font-size:13.5px;margin-right:14px;">Token usage</a>
  <a href="{url_for('jobs_index')}" style="float:right;font-weight:500;font-size:13.5px;margin-right:14px;">Recent jobs</a>
</div></div>
{body}
<script>
// Ambient job poller -- runs on EVERY dashboard page (this is the shared
// page shell), so a generation started from one posting still gets
// surfaced -- as a live topbar indicator while running, and a browser
// notification on completion -- no matter which page you've since
// navigated to. Only works while some BioHunter tab is open somewhere
// (plain polling, no server push -- see /jobs/active.json's docstring).
(function() {{
  const notifEnableLink = document.getElementById("notif-enable");
  const indicator = document.getElementById("job-indicator");

  function notifiedSet() {{
    try {{ return new Set(JSON.parse(localStorage.getItem("biohunter_notified_jobs") || "[]")); }}
    catch (e) {{ return new Set(); }}
  }}
  function markNotified(jobId) {{
    const s = notifiedSet(); s.add(jobId);
    // Cap stored size -- this is just dedup memory, not a real record.
    const arr = Array.from(s).slice(-200);
    localStorage.setItem("biohunter_notified_jobs", JSON.stringify(arr));
  }}

  if (window.Notification && Notification.permission === "default") {{
    notifEnableLink.style.display = "inline";
    notifEnableLink.onclick = function(e) {{
      e.preventDefault();
      Notification.requestPermission().then(function() {{
        notifEnableLink.style.display = "none";
      }});
    }};
  }}

  async function poll() {{
    let jobs;
    try {{
      const r = await fetch("/jobs/active.json");
      jobs = await r.json();
    }} catch (e) {{
      setTimeout(poll, 5000);
      return;
    }}

    const seen = notifiedSet();
    const running = jobs.filter(j => j.status === "running" || j.status === "queued");

    for (const j of jobs) {{
      if ((j.status === "done" || j.status === "error") && !seen.has(j.job_id)) {{
        markNotified(j.job_id);
        const label = (j.company_name || "Posting") + (j.job_title ? " \\u2014 " + j.job_title : "");
        if (window.Notification && Notification.permission === "granted") {{
          const n = new Notification(
            j.status === "done" ? "Resume ready" : "Generation failed",
            {{ body: label, tag: "biohunter-" + j.job_id }}
          );
          n.onclick = function() {{
            window.focus();
            if (j.posting_id) window.location = "/postings/" + j.posting_id;
          }};
        }}
      }}
    }}

    if (running.length === 0) {{
      indicator.textContent = "";
    }} else if (running.length === 1) {{
      const j = running[0];
      const pct = j.total_steps ? Math.round(100 * (j.step || 0) / j.total_steps) : null;
      indicator.innerHTML = '<a href="/postings/' + j.posting_id + '" style="color:inherit;">' +
        '\\u23f3 Generating' + (j.company_name ? ' for ' + j.company_name : '') +
        (pct !== null ? ' (' + pct + '%)' : '') + '</a>';
    }} else {{
      indicator.innerHTML = '<a href="/jobs" style="color:inherit;">\\u23f3 ' + running.length + ' generations running</a>';
    }}

    setTimeout(poll, running.length > 0 ? 3000 : 8000);
  }}
  poll();
}})();
</script>
</body>
</html>"""


def _score_badge(score: int | None) -> str:
    """Critic's resume-QUALITY score (drafts.final_score) -- only exists
    once a draft has been generated for a posting."""
    bucket = _score_bucket(score)
    label = f"{score}/10" if score is not None else "not generated"
    return f'<span class="badge badge--{bucket}">{_esc(label)}</span>'


def _fit_score_badge(score: float | None) -> str:
    """Scorer's job-FIT score (postings.score) -- exists once
    `biohunter score-postings` has scored this posting, independent of
    whether a draft has ever been generated for it. Kept visually
    distinct (labelled "fit") from _score_badge's resume-quality badge so
    the two scores this project deliberately keeps separate never look
    like the same number in the UI."""
    if score is None:
        return '<span class="badge badge--unknown">fit: n/a</span>'
    bucket = _score_bucket(int(round(score)))
    return f'<span class="badge badge--{bucket}">fit: {score:g}/10</span>'


# ---------------------------------------------------------------------------
# Postings-index filtering. Reuses cli.py's keyword_filter_match() and
# DEFAULT_BAY_AREA_LOCATIONS rather than a second implementation of the
# same substring-matching heuristic (see module docstring). Company/date/
# score are exact/range comparisons, so those stay as SQL WHERE clauses;
# title-keyword and location matching stay in Python post-query, same
# division cmd_list_postings itself already uses -- consistent behavior
# beats a cleverer-but-different SQL LIKE reimplementation.
# ---------------------------------------------------------------------------


def _parse_filters(args) -> dict:
    keyword = (args.get("keyword") or "").strip()
    location_kw = (args.get("location") or "").strip()
    return {
        "keyword": keyword,
        "keyword_list": [k.strip().lower() for k in keyword.split(",") if k.strip()],
        "location": location_kw,
        "location_list": [k.strip().lower() for k in location_kw.split(",") if k.strip()],
        "bay_area": args.get("bay_area") == "1",
        "company": (args.get("company") or "").strip(),
        "date_from": (args.get("date_from") or "").strip(),
        "date_to": (args.get("date_to") or "").strip(),
        "min_score": (args.get("min_score") or "").strip(),
        "draft_status": args.get("draft_status") if args.get("draft_status") in ("has", "none") else "",
        "page": max(1, int(args.get("page") or 1)) if str(args.get("page") or "1").isdigit() else 1,
    }


def _filters_query_string(filters: dict, **overrides) -> str:
    """Rebuilds the query string for pagination links, carrying every
    active filter forward except the ones being overridden (e.g. page)."""
    merged = {
        "keyword": filters["keyword"], "location": filters["location"],
        "bay_area": "1" if filters["bay_area"] else "", "company": filters["company"],
        "date_from": filters["date_from"], "date_to": filters["date_to"],
        "min_score": filters["min_score"], "draft_status": filters["draft_status"], "page": filters["page"],
    }
    merged.update(overrides)
    from urllib.parse import urlencode
    return urlencode({k: v for k, v in merged.items() if v not in (None, "", 0)})


def _distinct_companies(conn) -> list[str]:
    # INNER JOIN, not a plain SELECT DISTINCT on companies -- a company
    # with zero postings (e.g. one created by a manual/extension capture
    # whose only posting was later deleted) should just disappear from
    # this filter dropdown on its own, rather than needing an explicit
    # "delete company" action. A company with any posting still shows,
    # even if that posting is status='stale', same as before this change.
    rows = conn.execute(
        """SELECT DISTINCT companies.name
           FROM companies
           INNER JOIN postings ON postings.company_id = companies.id
           ORDER BY companies.name"""
    ).fetchall()
    return [r[0] for r in rows]


def _filter_bar_html(filters: dict, companies: list[str]) -> str:
    company_options = ['<option value="">All companies</option>']
    for name in companies:
        selected = " selected" if name == filters["company"] else ""
        company_options.append(f'<option value="{_esc(name)}"{selected}>{_esc(name)}</option>')

    return f"""<form class="filter-bar" method="get" action="{url_for('index')}">
  <div class="field"><label for="f-keyword">Keyword (title)</label>
    <input type="text" id="f-keyword" name="keyword" value="{_esc(filters['keyword'])}" placeholder="e.g. mass spec, scientist"></div>
  <div class="field"><label for="f-location">Location keyword</label>
    <input type="text" id="f-location" name="location" value="{_esc(filters['location'])}" placeholder="e.g. remote, san diego"></div>
  <div class="field checkbox-field">
    <input type="checkbox" id="f-bay-area" name="bay_area" value="1" {"checked" if filters['bay_area'] else ""}>
    <label for="f-bay-area">Bay Area only</label></div>
  <div class="field"><label for="f-company">Company</label>
    <select id="f-company" name="company">{''.join(company_options)}</select></div>
  <div class="field"><label for="f-date-from">First seen from</label>
    <input type="date" id="f-date-from" name="date_from" value="{_esc(filters['date_from'])}"></div>
  <div class="field"><label for="f-date-to">First seen to</label>
    <input type="date" id="f-date-to" name="date_to" value="{_esc(filters['date_to'])}"></div>
  <div class="field"><label for="f-min-score">Min fit score</label>
    <input type="number" id="f-min-score" name="min_score" min="1" max="10" value="{_esc(filters['min_score'])}" style="width:56px;"></div>
  <div class="field"><label for="f-draft-status">Draft status</label>
    <select id="f-draft-status" name="draft_status">
      <option value="" {"selected" if not filters['draft_status'] else ""}>Any</option>
      <option value="has" {"selected" if filters['draft_status'] == 'has' else ""}>Has draft</option>
      <option value="none" {"selected" if filters['draft_status'] == 'none' else ""}>No draft yet</option>
    </select></div>
  <div class="actions">
    <button class="btn btn--small" type="submit">Apply</button>
    <a class="btn btn--secondary btn--small" href="{url_for('index')}">Clear</a>
  </div>
</form>"""


def _score_batch_form_html(filters: dict, matched_count: int) -> str:
    """POSTs the CURRENT filter state (as hidden fields, exact mirror of
    what _filter_bar_html's GET form holds) to /postings/score-batch, so
    Scorer runs over exactly the filtered set the cards were rendered
    from -- see _filtered_postings()'s docstring for why this isn't a
    second filter implementation."""
    if matched_count == 0:
        return ""
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{_esc(str(value))}">'
        for name, value in [
            ("keyword", filters["keyword"]), ("location", filters["location"]),
            ("bay_area", "1" if filters["bay_area"] else ""), ("company", filters["company"]),
            ("date_from", filters["date_from"]), ("date_to", filters["date_to"]),
            ("min_score", filters["min_score"]), ("draft_status", filters["draft_status"]),
        ] if value
    )
    return f"""<form class="score-batch-bar" method="post" action="{url_for('score_batch_route')}">
  {hidden}
  <span>Score these <strong>{matched_count}</strong> filtered posting(s) with Scorer</span>
  <div class="checkbox-field">
    <input type="checkbox" id="sb-rescore" name="rescore" value="1">
    <label for="sb-rescore">Include already-scored (rescore)</label>
  </div>
  <button class="btn btn--small" type="submit">Score filtered postings</button>
</form>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _filtered_postings(conn, filters: dict, drafts_by_posting: dict | None = None) -> tuple[list[tuple], list[tuple]]:
    """The SQL query + keyword/location filtering index() has always done,
    extracted so POST /postings/score-batch can run Scorer over EXACTLY
    the same filtered set the cards were rendered from -- one filtering
    implementation, two callers, not a second filter UI/logic path per
    the 2026-08-10 handoff's explicit instruction.

    2026-08-23 addition: draft_status ("has"/"none"/"" for any) filters
    against drafts_by_posting (drafts_db.latest_draft_index()) -- passed
    in by callers that already have it (index()) so it isn't queried
    twice per request; computed here if a caller doesn't have it yet
    (score_batch_route()), so BOTH callers apply the SAME draft filter
    rather than index() alone drifting from what Scorer actually runs
    over.

    Returns (all_rows, filtered_rows); each row is (id, company, title,
    location, status, score, first_seen_at, description) -- description
    added (index() itself doesn't use it, only ignores the extra column)
    so score-batch doesn't need a second query to fetch it.
    """
    query = """
        SELECT postings.id, companies.name, postings.title, postings.location,
               postings.status, postings.score, postings.first_seen_at, postings.description
        FROM postings JOIN companies ON postings.company_id = companies.id
        WHERE postings.status != 'stale'
    """
    params: list = []
    if filters["company"]:
        query += " AND companies.name = ?"
        params.append(filters["company"])
    if filters["date_from"]:
        query += " AND date(postings.first_seen_at) >= date(?)"
        params.append(filters["date_from"])
    if filters["date_to"]:
        query += " AND date(postings.first_seen_at) <= date(?)"
        params.append(filters["date_to"])
    if filters["min_score"]:
        query += " AND postings.score >= ?"
        params.append(float(filters["min_score"]))
    query += " ORDER BY companies.name, postings.title"

    all_rows = conn.execute(query, tuple(params)).fetchall()

    location_include = DEFAULT_BAY_AREA_LOCATIONS if filters["bay_area"] else filters["location_list"]
    filtered_rows = [
        row for row in all_rows
        if keyword_filter_match(row[2], filters["keyword_list"], [])
        and keyword_filter_match(row[3] or "", location_include, [])
    ]

    if filters.get("draft_status") in ("has", "none"):
        if drafts_by_posting is None:
            drafts_by_posting = drafts_db.latest_draft_index(conn)
        if filters["draft_status"] == "has":
            filtered_rows = [row for row in filtered_rows if row[0] in drafts_by_posting]
        else:
            filtered_rows = [row for row in filtered_rows if row[0] not in drafts_by_posting]

    return all_rows, filtered_rows


@app.route("/")
def index():
    conn = get_connection()
    init_schema(conn)

    filters = _parse_filters(request.args)
    drafts_by_posting = drafts_db.latest_draft_index(conn)
    all_rows, filtered_rows = _filtered_postings(conn, filters, drafts_by_posting)

    companies = _distinct_companies(conn)
    filter_bar = _filter_bar_html(filters, companies)

    total = len(filtered_rows)
    per_page = POSTINGS_PER_PAGE
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(filters["page"], total_pages)
    page_rows = filtered_rows[(page - 1) * per_page : page * per_page]

    add_manual_link = f'<a class="btn btn--secondary btn--small" href="{url_for("posting_manual_form")}">+ Add posting manually</a>'
    # Combined Scout + dead-link-check button (Captain roadmap #4, direct
    # request): the two used to be separate buttons/routes. Kept as one
    # action now -- no point applying to a posting Scout would've just
    # found is gone. The two old routes (run_scout_route/
    # check_dead_links_route) and their standalone runners are still in
    # the file and still work if you navigate to them directly; only the
    # index page's default path changed.
    scout_and_check_form = f"""<form method="post" action="{url_for('scout_and_check_route')}" class="inline-form">
      <button class="btn btn--small" type="submit"
        title="Runs Scout (find new postings, mark stale anything gone from a company's page), then checks every remaining posting's URL for a real HTTP 404/410 -- can take a while.">
        Run Scout + check links</button></form>"""
    recent_jobs_link = f'<a class="btn btn--small btn--secondary" href="{url_for("jobs_index")}">Recent jobs</a>'
    score_batch_form = _score_batch_form_html(filters, total)

    if not all_rows:
        body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Postings</h1>{scout_and_check_form}{recent_jobs_link}</div>
  {filter_bar}
  <div class="empty-state">No postings yet — click Run Scout + check links above, or {add_manual_link}.</div>
</div>"""
        return _page("Postings", body)

    # Captain roadmap #6 fix (2026-08-23): the index cards previously
    # decided their link purely from `draft` presence, never checking
    # whether a generate job was already in flight for that posting --
    # unlike posting_detail(), which has always guarded on this via
    # _active_generate_job_for_posting(). Snapshot both active-job sets
    # ONCE here (one _jobs_lock acquisition) rather than calling those
    # per-posting helpers inside the loop below (which would re-acquire
    # the lock once per card, up to POSTINGS_PER_PAGE times per request).
    with _jobs_lock:
        active_generate_ids = {
            j.get("posting_id") for j in _jobs.values()
            if j.get("kind") == "generate" and j.get("status") in _ACTIVE_STATUSES
        }
        active_batch_ids: set[int] = set()
        for j in _jobs.values():
            if j.get("kind") == "batch_generate" and j.get("status") in _ACTIVE_STATUSES:
                active_batch_ids.update(j.get("posting_ids") or [])
    active_posting_ids = active_generate_ids | active_batch_ids

    cards = []
    for posting_id, company, title, location, status, score, _first_seen_at, _description in page_rows:
        draft = drafts_by_posting.get(posting_id)
        quality_score = draft.final_score if draft else None
        is_generating = posting_id in active_posting_ids
        if draft:
            link = f'<a class="card__link" href="{url_for("posting_detail", posting_id=posting_id)}">View result</a>'
        elif is_generating:
            # Still links to posting_detail -- that page shows the real
            # live progress panel via its own in-flight check. This card
            # just needs to stop claiming "Generate" is available.
            link = f'<a class="card__link" href="{url_for("posting_detail", posting_id=posting_id)}">Generating…</a>'
        else:
            link = f'<a class="card__link" href="{url_for("posting_detail", posting_id=posting_id)}">Generate</a>'
        checkbox_disabled = " disabled" if is_generating else ""
        cards.append(
            f"""<div class="card">
  <label class="card__select" style="font-size:12px;color:var(--ink-faint);display:flex;align-items:center;gap:6px;">
    <input type="checkbox" name="posting_ids" value="{posting_id}" form="batch-form" onchange="updateBatchBar()"{checkbox_disabled}> select
  </label>
  <div class="card__company">{_esc(company)}</div>
  <h3 class="card__title">{_esc(title)}</h3>
  <div class="card__meta">{_esc(location or 'Location n/a')} &middot; status: {_esc(status)}</div>
  <div class="card__footer">{_fit_score_badge(score)}{_score_badge(quality_score)}{link}</div>
</div>"""
        )

    pagination_html = ""
    if total_pages > 1:
        links = []
        for p in range(1, total_pages + 1):
            if p == page:
                links.append(f'<span class="current">{p}</span>')
            else:
                qs = _filters_query_string(filters, page=p)
                links.append(f'<a href="{url_for("index")}?{qs}">{p}</a>')
        pagination_html = f'<div class="pagination">{"".join(links)}</div>'

    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Postings</h1>{scout_and_check_form}{recent_jobs_link}
    <p class="sub">{total} posting(s) match &middot; {len(all_rows)} total (excluding stale) &middot; {add_manual_link}</p></div>
  {filter_bar}
  {score_batch_form}
  <form method="post" action="{url_for('batch_generate_confirm')}" id="batch-form" class="score-batch-bar">
    <span>Select postings above, then generate resume + cover letter for each in sequence.</span>
    <button class="btn btn--small" type="submit" id="batch-generate-btn" disabled>Generate selected (0)</button>
  </form>
  <p class="sub" style="margin-top:-14px;margin-bottom:16px;">Selection only applies to postings shown on this page (pagination isn't select-all-aware yet).</p>
  <div class="grid">{''.join(cards)}</div>
  {pagination_html}
</div>
<script>
function updateBatchBar() {{
  const checked = document.querySelectorAll('input[name="posting_ids"][form="batch-form"]:checked').length;
  const btn = document.getElementById("batch-generate-btn");
  if (btn) {{ btn.textContent = "Generate selected (" + checked + ")"; btn.disabled = checked === 0; }}
}}
</script>"""
    return _page("Postings", body)


def _history_panel_html(conn, posting_id: int) -> str:
    """Flattens `drafts` (every generation event) and `archived_edit`
    (every hand-edit archived when Regenerate was clicked before it was
    saved-as-final or reset) into one chronologically descending list --
    the exact shape archived_edit's own schema.sql comment already
    calls for ("flattened chronologically alongside drafts.result_json's
    own rounds, labeled there as \'your edit, before regenerating\'").

    Each entry is its own nested <details> so opening the panel doesn't
    dump every past resume/cover-letter version onto the page at once --
    same disclosure pattern as the editor panel above it.
    """
    drafts = drafts_db.list_drafts_for_posting(conn, posting_id)
    archived = drafts_db.list_archived_edits_for_posting(conn, posting_id)

    entries = [(d.generated_at, "draft", d) for d in drafts]
    entries += [(a["archived_at"], "archived_edit", a) for a in archived]
    entries.sort(key=lambda e: e[0], reverse=True)

    if not entries:
        return ""

    rows = []
    for _, kind, item in entries:
        if kind == "draft":
            fd = item.result.final_draft
            score = item.final_score if item.final_score is not None else "?"
            label = (
                f"Draft &middot; generated {_esc(item.generated_at)} &middot; "
                f"score {score}/10 &middot; {item.revision_rounds + 1} round(s)"
            )
            summary_text, bullets_text, cover_text = (
                fd.tailored_summary, fd.tailored_bullets, fd.cover_letter,
            )
        else:
            label = (
                f"Your edit, before regenerating &middot; edited {_esc(item['edited_at'])} "
                f"&middot; archived {_esc(item['archived_at'])}"
            )
            summary_text, bullets_text, cover_text = (
                item["tailored_summary"], item["tailored_bullets"], item["cover_letter"],
            )
        rows.append(f"""<details class="history-entry">
  <summary>{label}</summary>
  <div class="history-entry__body">
    <p class="history-entry__field-label">Tailored summary</p>
    <p class="history-entry__text">{_esc(summary_text or "")}</p>
    <p class="history-entry__field-label">Tailored bullets</p>
    <p class="history-entry__text">{_esc(bullets_text or "")}</p>
    <p class="history-entry__field-label">Cover letter</p>
    <p class="history-entry__text">{_esc(cover_text or "")}</p>
  </div>
</details>""")

    return f"""<details class="editor-panel" style="margin-top:16px;">
  <summary>Version history ({len(entries)})</summary>
  {"".join(rows)}
</details>"""


@app.route("/postings/<int:posting_id>")
def posting_detail(posting_id):
    conn = get_connection()
    init_schema(conn)
    posting = _get_posting(conn, posting_id)
    if posting is None:
        abort(404)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    edit = drafts_db.get_final_edit(conn, posting_id) if draft is not None else None

    apply_link = (
        f' &middot; <a href="{_esc(posting["apply_url"])}" target="_blank"><strong>apply here</strong></a>'
        if posting.get("apply_url")
        else ""
    )
    header = f"""<div class="detail-header">
  <h1>{_esc(posting['title'])}</h1>
  <p class="sub">{_esc(posting['company'])} &middot; {_esc(posting['location'] or 'Location n/a')}
  &middot; <a href="{_esc(posting['url'])}" target="_blank">original posting</a>{apply_link}</p>
</div>
<form method="post" action="{url_for('mark_stale_route')}" class="inline-form" style="margin-top:8px;">
  <input type="hidden" name="posting_id" value="{posting_id}">
  <input type="hidden" name="redirect_to" value="{url_for('index')}">
  <button class="btn btn--secondary btn--small" type="submit"
    title="If the 'original posting' link above is dead, mark this posting stale so it drops out of the normal list.">
    Mark as stale (link is dead)</button>
</form>
<form method="post" action="{url_for('delete_posting_route')}" class="inline-form" style="margin-top:8px;"
  onsubmit="return confirm('Permanently delete this posting{" and its generated draft" if draft is not None else ""}? This can\\'t be undone.');">
  <input type="hidden" name="posting_id" value="{posting_id}">
  <input type="hidden" name="redirect_to" value="{url_for('index')}">
  <button class="btn btn--secondary btn--small" type="submit" style="color:#b00020;border-color:#b00020;"
    title="Permanently remove this posting (and any draft/application/outreach tied to it). Unlike Mark as stale, this can't be undone.">
    Delete posting</button>
</form>"""

    if not posting["description"]:
        jd_form = f"""<form method="post" action="{url_for('generate', posting_id=posting_id)}">
  <label for="description">Job description (not yet stored for this posting — paste it once, it'll be saved)</label>
  <textarea class="jd-box" name="description" id="description" required></textarea>
  {_generate_options_html()}
  <div class="btn-row"><button class="btn" type="submit">Generate draft</button></div>
</form>"""
        return _page(posting["title"], f'<div class="dash-wrap">{header}{jd_form}</div>')

    result_html = ""
    if draft is not None:
        score_result = ScoreResult(score=draft.final_score, rationale=None)
        rationale = parse_score(draft.result.final_critique).rationale or ""
        bucket = _score_bucket(draft.final_score)
        value = draft.final_score if draft.final_score is not None else "?"
        result_html = f"""<div class="result-summary">
  <div class="dial dial--{bucket}"><div class="dial__value">{value}<span class="dial__max">/10</span></div>
  <div class="dial__label">Latest score</div></div>
  <p class="dial__rationale">{_esc(rationale)}</p>
</div>
<div class="btn-row">
  <a class="btn" href="{url_for('posting_report', posting_id=posting_id)}">View full report</a>
  <a class="btn btn--secondary" href="{url_for('posting_resume_preview', posting_id=posting_id)}" target="_blank">Preview resume</a>
  <a class="btn btn--secondary" href="{url_for('posting_resume_pdf', posting_id=posting_id)}">Download resume PDF</a>
  <a class="btn btn--secondary" href="{url_for('posting_cover_letter_preview', posting_id=posting_id)}" target="_blank">Preview cover letter</a>
  <a class="btn btn--secondary" href="{url_for('posting_cover_letter_pdf', posting_id=posting_id)}">Download cover letter PDF</a>
</div>
<p class="sub" style="margin-top:10px;">Generated {_esc(draft.generated_at)} &middot; {draft.revision_rounds + 1} round(s)</p>"""

    editor_html = ""
    if draft is not None:
        # Seeded from the active hand edit if one exists (final_edit,
        # drafts_db.py), otherwise from the latest AI draft's own fields
        # -- "the first time you click Edit" per the roadmap's wording.
        # Deliberately does NOT touch cover_letter_blocks -- the editor
        # only exposes the three assembled sections as plain textareas.
        if edit is not None:
            cur_summary = edit["tailored_summary"] or ""
            cur_bullets = edit["tailored_bullets"] or ""
            cur_cover = edit["cover_letter"] or ""
            edited_badge = f' <span class="edited-badge">(edited {_esc(edit["edited_at"])})</span>'
            reset_form = f"""<form method="post" action="{url_for('reset_edit', posting_id=posting_id)}"
  style="margin-top:10px;"
  onsubmit="return confirm('Discard your edits and revert to the AI draft? This can\\'t be undone.');">
  <button class="btn btn--secondary btn--small" type="submit">Reset to AI draft</button>
</form>"""
        else:
            cur_summary = draft.result.final_draft.tailored_summary or ""
            cur_bullets = draft.result.final_draft.tailored_bullets or ""
            cur_cover = draft.result.final_draft.cover_letter or ""
            edited_badge = ""
            reset_form = ""
        editor_html = f"""<details class="editor-panel" style="margin-top:16px;"{' open' if edit is not None else ''}>
  <summary>Edit resume &amp; cover letter{edited_badge}</summary>
  <form method="post" action="{url_for('save_edit', posting_id=posting_id)}">
    <div class="editor-field">
      <label for="edit_summary">Tailored summary</label>
      <textarea class="editor-box" name="tailored_summary" id="edit_summary">{_esc(cur_summary)}</textarea>
    </div>
    <div class="editor-field">
      <label for="edit_bullets">Tailored bullets</label>
      <textarea class="editor-box" name="tailored_bullets" id="edit_bullets">{_esc(cur_bullets)}</textarea>
    </div>
    <div class="editor-field">
      <label for="edit_cover">Cover letter</label>
      <textarea class="editor-box" name="cover_letter" id="edit_cover">{_esc(cur_cover)}</textarea>
    </div>
    <div class="btn-row" style="margin-top:14px;"><button class="btn" type="submit">Save edit</button></div>
  </form>
  {reset_form}
</details>"""

    history_html = _history_panel_html(conn, posting_id) if draft is not None else ""

    active_job = _active_generate_job_for_posting(posting_id)
    active_batch = _active_batch_job_for_posting(posting_id) if active_job is None else None

    jd_full = _esc(posting["description"])
    regenerate_label = "Regenerate" if draft is not None else "Generate draft"

    if active_batch is not None:
        gen_form = f"""<details style="margin-top:24px;"><summary style="cursor:pointer;font-weight:600;">Job description (stored)</summary>
  <p class="sub" style="white-space:pre-wrap;">{jd_full}</p></details>
<div class="progress-panel" style="margin-top:16px;">
  <p style="font-weight:600;margin:0 0 6px;">Part of a batch generation currently running</p>
  <p class="sub">This posting is queued as part of a multi-posting batch (running one at a time).
  <a href="{url_for('job_status_page', job_id=active_batch['job_id'])}">View batch progress</a></p>
</div>"""
    elif active_job is not None:
        total_steps = active_job.get("total_steps") or 0
        step = active_job.get("step") or 0
        pct = int(100 * step / total_steps) if total_steps else 0
        current_label = _esc(active_job.get("current") or "starting…")
        gen_form = f"""<details style="margin-top:24px;"><summary style="cursor:pointer;font-weight:600;">Job description (stored)</summary>
  <p class="sub" style="white-space:pre-wrap;">{jd_full}</p></details>
<div class="progress-panel" style="margin-top:16px;" data-job-id="{_esc(active_job['job_id'])}">
  <p style="font-weight:600;margin:0 0 6px;">{'Regenerating' if draft is not None else 'Generating'}…</p>
  <progress id="gen-progress" value="{step}" max="{total_steps or 1}" style="width:100%;height:10px;"></progress>
  <p id="gen-progress-label" class="sub" style="margin-top:6px;">{current_label} ({step}/{total_steps or '?'})</p>
</div>
<script>
(function() {{
  const jobId = "{active_job['job_id']}";
  async function poll() {{
    const r = await fetch("/jobs/" + jobId + ".json");
    if (!r.ok) {{ setTimeout(poll, 2500); return; }}
    const j = await r.json();
    if (j.status === "done" || j.status === "error") {{
      window.location.reload();
      return;
    }}
    const bar = document.getElementById("gen-progress");
    const label = document.getElementById("gen-progress-label");
    if (bar && j.total_steps) {{ bar.max = j.total_steps; bar.value = j.step || 0; }}
    if (label) {{ label.textContent = (j.current || "working…") + " (" + (j.step || 0) + "/" + (j.total_steps || "?") + ")"; }}
    setTimeout(poll, 2000);
  }}
  poll();
}})();
</script>"""
    else:
        gen_form = f"""<details style="margin-top:24px;" open><summary style="cursor:pointer;font-weight:600;">Job description (stored)</summary>
  <p class="sub" style="white-space:pre-wrap;">{jd_full}</p></details>
<form method="post" action="{url_for('generate', posting_id=posting_id)}" style="margin-top:16px;">
  {_generate_options_html()}
  <div class="btn-row"><button class="btn" type="submit">{regenerate_label}</button></div>
</form>"""

    body = f'<div class="dash-wrap">{header}{result_html}{editor_html}{history_html}{gen_form}</div>'
    return _page(posting["title"], body)


@app.route("/postings/<int:posting_id>/edit", methods=["POST"])
def save_edit(posting_id):
    """Saves the current hand edit for this posting's resume/cover letter
    into `final_edit` (drafts_db.py) -- upserted in place, always the
    CURRENT edit, never a history (see that table's schema.sql comment).
    Requires the posting to exist; the editor panel is only ever shown
    once a draft has been generated, but this guards a stale
    tab/direct POST after a posting is deleted.
    """
    conn = get_connection()
    init_schema(conn)
    posting = _get_posting(conn, posting_id)
    if posting is None:
        abort(404)
    tailored_summary = request.form.get("tailored_summary", "")
    tailored_bullets = request.form.get("tailored_bullets", "")
    cover_letter = request.form.get("cover_letter", "")
    drafts_db.save_final_edit(conn, posting_id, tailored_summary, tailored_bullets, cover_letter)
    return redirect(url_for("posting_detail", posting_id=posting_id))


@app.route("/postings/<int:posting_id>/edit/reset", methods=["POST"])
def reset_edit(posting_id):
    """Discards the current hand edit, reverting the editor panel (and,
    once preview/PDF export are wired to read final_edit next, those
    too) back to the latest AI draft's own content.
    """
    conn = get_connection()
    init_schema(conn)
    drafts_db.clear_final_edit(conn, posting_id)
    return redirect(url_for("posting_detail", posting_id=posting_id))


def _generate_options_html() -> str:
    return """<div class="form-row">
  <label>Revision rounds (after first draft): <input type="number" name="revision_rounds" value="1" min="0" max="5"></label>
  <label><input type="checkbox" name="think"> Thorough mode (slower, "thinking" on)</label>
</div>
<div class="form-row">
  <label for="stability">How much should revisions deviate from your original materials?</label>
  <select id="stability" name="stability">
    <option value="strict">Stay close to my materials (small tweaks only)</option>
    <option value="balanced" selected>Balanced (default)</option>
    <option value="loose">Optimize for this job description (more willing to change)</option>
  </select>
</div>"""


@app.route("/postings/<int:posting_id>/generate", methods=["POST"])
def generate(posting_id):
    conn = get_connection()
    init_schema(conn)
    posting = _get_posting(conn, posting_id)
    if posting is None:
        abort(404)

    # Regenerate-while-editing handling (Writer subsystem #4): an
    # in-progress hand edit must never be silently overwritten by the
    # fresh draft this call is about to create, nor silently left in
    # final_edit to collide with it. No-ops (returns False) for a first
    # Generate, since the editor panel only exists once a draft already
    # does -- see archive_final_edit()'s own docstring.
    drafts_db.archive_final_edit(conn, posting_id)

    description = (request.form.get("description") or "").strip() or posting["description"]
    if not description:
        return _page("Error", '<div class="dash-wrap"><p>No job description available — paste one first.</p></div>'), 400

    if description != posting["description"]:
        conn.execute("UPDATE postings SET description = ? WHERE id = ?", (description, posting_id))
        conn.commit()

    try:
        revision_rounds = int(request.form.get("revision_rounds", 1))
    except ValueError:
        revision_rounds = 1
    think = request.form.get("think") == "on"
    stability = request.form.get("stability") or "balanced"
    if stability not in ("strict", "balanced", "loose"):
        stability = "balanced"

    job_id = uuid.uuid4().hex[:12]
    _set_job(
        job_id, status="queued", posting_id=posting_id, kind="generate",
        company_name=posting["company"], job_title=posting["title"],
    )
    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, posting_id, posting["company"], posting["title"], description,
              revision_rounds, think, stability),
        daemon=True,
    )
    thread.start()
    return redirect(url_for("posting_detail", posting_id=posting_id))


@app.route("/postings/batch-generate/confirm", methods=["POST"])
def batch_generate_confirm():
    """Confirmation step between the postings-index checkboxes and
    actually starting the batch job -- explicit user decision, not a
    convenience skip that was assumed. Any selected posting that
    ALREADY has a draft is flagged with a note and left checked by
    default (batch generation adds a new draft row, same as clicking
    Regenerate today -- it never overwrites), but you can uncheck it
    here before anything actually runs.

    Selected postings with no stored job description are silently
    excluded from the checklist below and listed read-only instead --
    batch generation has no per-posting paste step, so there's no
    reasonable way to collect a description for them here; open them
    individually to add one first."""
    posting_ids = [int(x) for x in request.form.getlist("posting_ids") if x.isdigit()]
    if not posting_ids:
        return redirect(url_for("index"))

    conn = get_connection()
    init_schema(conn)
    drafts_by_posting = drafts_db.latest_draft_index(conn)

    ready_rows = []
    skipped_rows = []
    for pid in posting_ids:
        posting = _get_posting(conn, pid)
        if posting is None:
            continue
        if not posting["description"]:
            skipped_rows.append(posting)
            continue
        ready_rows.append((posting, drafts_by_posting.get(pid)))

    if not ready_rows:
        body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Batch generation</h1></div>
  <p>None of the selected posting(s) have a stored job description, so there's nothing to batch-generate.
  Open each one individually to paste a description first.</p>
  <p><a class="btn btn--small btn--secondary" href="{url_for('index')}">Back to postings</a></p>
</div>"""
        return _page("Batch generation", body)

    items_html = []
    for posting, draft in ready_rows:
        note = ""
        if draft is not None:
            note = (
                f'<br><span class="sub" style="color:#b00020;">already has a draft '
                f'(generated {_esc(draft.generated_at)}) &mdash; this will add a NEW draft, not overwrite it</span>'
            )
        items_html.append(f"""<div class="card" style="padding:12px 16px;">
  <label style="display:flex;align-items:flex-start;gap:10px;">
    <input type="checkbox" name="posting_ids" value="{posting['id']}" checked style="margin-top:3px;">
    <span><strong>{_esc(posting['company'])}</strong> &mdash; {_esc(posting['title'])}{note}</span>
  </label>
</div>""")

    skipped_html = ""
    if skipped_rows:
        skipped_items = "".join(
            f'<li><a href="{url_for("posting_detail", posting_id=p["id"])}">{_esc(p["company"])} '
            f'&mdash; {_esc(p["title"])}</a> (no job description stored)</li>'
            for p in skipped_rows
        )
        skipped_html = f"""<div class="sub" style="margin-top:20px;">
  <p>{len(skipped_rows)} selected posting(s) skipped &mdash; no job description stored:</p>
  <ul>{skipped_items}</ul>
</div>"""

    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Confirm batch generation</h1></div>
  <p class="sub">Generates one posting at a time, in the order below &mdash; not in parallel, to protect the
  local model's KV cache. This can take a while for several postings; you'll get a real progress view once it starts.</p>
  <form method="post" action="{url_for('batch_generate_start')}">
    <div class="grid" style="grid-template-columns:1fr;gap:8px;">{''.join(items_html)}</div>
    {_generate_options_html()}
    <p class="sub" style="margin-top:6px;">These settings apply to every posting in this batch.</p>
    <div class="btn-row" style="margin-top:14px;">
      <button class="btn" type="submit">Start batch generation</button>
      <a class="btn btn--secondary" href="{url_for('index')}">Cancel</a>
    </div>
  </form>
  {skipped_html}
</div>"""
    return _page("Confirm batch generation", body)


@app.route("/postings/batch-generate/start", methods=["POST"])
def batch_generate_start():
    """Starts the actual background thread -- only reached from
    batch_generate_confirm()'s form, after the user has seen and
    confirmed the exact posting list (including any already-drafted
    ones they chose to keep checked)."""
    posting_ids = [int(x) for x in request.form.getlist("posting_ids") if x.isdigit()]
    if not posting_ids:
        return redirect(url_for("index"))

    try:
        revision_rounds = int(request.form.get("revision_rounds", 1))
    except ValueError:
        revision_rounds = 1
    think = request.form.get("think") == "on"
    stability = request.form.get("stability") or "balanced"
    if stability not in ("strict", "balanced", "loose"):
        stability = "balanced"

    conn = get_connection()
    init_schema(conn)
    items = []
    for pid in posting_ids:
        posting = _get_posting(conn, pid)
        if posting is not None and posting["description"]:
            items.append({
                "posting_id": pid, "company": posting["company"],
                "title": posting["title"], "description": posting["description"],
            })

    if not items:
        return redirect(url_for("index"))

    job_id = uuid.uuid4().hex[:12]
    _set_job(
        job_id, status="queued", kind="batch_generate",
        posting_ids=[it["posting_id"] for it in items], total=len(items),
    )
    thread = threading.Thread(
        target=_run_batch_generation,
        args=(job_id, items, revision_rounds, think, stability),
        daemon=True,
    )
    thread.start()
    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job_route(job_id):
    """Requests cancellation of a running/queued job -- sets a flag the
    job's own loop checks at its next safe point (between postings for
    batch_generate/score_batch, between URLs for dead_link_check, between
    companies for scout). This is a REQUEST, not an interrupt: the item
    currently in flight (an LLM call, an HTTP check, a company's fetch)
    still finishes; nothing stops mid-call.

    Scout support added 2026-08-23 once detector.py's run_scout() gained
    a should_stop hook (checked once per company, same boundary
    on_company_done already fires at) -- see run_scout()'s own docstring.

    Single-posting 'generate' support added same day via a different
    mechanism (see _JobCancelled's docstring): no Python-level loop to
    check between iterations here, so cancellation is raised from inside
    the on_step callback instead. Code-level trace now COMPLETE (writer.py
    and selection.py both seen): every on_step call in the chain is bare,
    no try/except anywhere between _step() and run_revision_loop(), so
    _JobCancelled propagates cleanly regardless of which of the 10 units
    of work per round is running when Cancel is clicked. Still worth one
    real click-test to confirm live (see handoff), but there's no
    remaining code-level uncertainty.

    'scout_and_check' support added same session as the combined-job
    feature -- cancel_requested is checked at both phase boundaries
    (between companies during the scout phase, between posting URLs
    during the dead-link phase), same field, same mechanism, no new
    cancellation logic needed."""
    job = _get_job(job_id)
    if job is not None and job.get("kind") in ("batch_generate", "score_batch", "dead_link_check", "scout", "generate", "scout_and_check"):
        _set_job(job_id, cancel_requested=True)
    redirect_to = request.form.get("redirect_to") or url_for("jobs_index")
    return redirect(redirect_to)


@app.route("/scout/run", methods=["POST"])
def run_scout_route():
    """2026-08-10: dashboard-triggered Scout, reversing the CLI-only
    precedent -- see module docstring. Same job-thread mechanism as
    generate(); run_scout() itself takes no arguments (it reads
    companies.yaml on its own, same as cmd_run_scout), so there's no
    form data to read here."""
    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", kind="scout")
    thread = threading.Thread(target=_run_scout_job, args=(job_id,), daemon=True)
    thread.start()
    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/scout-and-check/run", methods=["POST"])
def scout_and_check_route():
    """Combined Scout + dead-link-check, Captain roadmap item #4. Same
    job-thread mechanism as every other job kind; run_scout() itself
    takes no arguments, same as run_scout_route(), so there's no form
    data to read here either -- the dead-link sweep's posting set is
    computed fresh inside _run_scout_and_check_job() AFTER Scout finishes,
    not passed in from here, since Scout may have just changed which
    postings are non-stale."""
    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", kind="scout_and_check", phase="scout")
    thread = threading.Thread(target=_run_scout_and_check_job, args=(job_id,), daemon=True)
    thread.start()
    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/postings/score-batch", methods=["POST"])
def score_batch_route():
    """2026-08-10: dashboard-triggered Scorer over the CURRENT filter set
    -- reversing scorer.py's own "CLI-only" precedent, see module
    docstring. Re-derives filters from the posted hidden fields (same
    _parse_filters()/_filtered_postings() index() itself uses) rather
    than trusting a posting-id list from the client, so the scored set
    can never drift from what the filter bar actually shows."""
    conn = get_connection()
    init_schema(conn)
    filters = _parse_filters(request.form)
    _all_rows, filtered_rows = _filtered_postings(conn, filters)
    # Drop score/first_seen_at (index columns _run_score_batch doesn't need);
    # keep id/company/title/location/status/description in that order.
    posting_rows = [(r[0], r[1], r[2], r[3], r[4], r[7]) for r in filtered_rows]
    rescore = request.form.get("rescore") == "1"
    think = request.form.get("think") == "on"

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", kind="score_batch", total=len(posting_rows), scored=0, skipped=0)
    thread = threading.Thread(
        target=_run_score_batch, args=(job_id, posting_rows, rescore, think), daemon=True,
    )
    thread.start()
    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/postings/check-dead-links", methods=["POST"])
def check_dead_links_route():
    """Scans EVERY non-stale posting in the DB (not just the current
    filter view -- the whole-database sweep the person asked for
    separately from the per-posting 'mark as stale' button), checking
    each stored URL for a real HTTP 404/410. Same job-thread mechanism
    as Scout/score-batch, not a new pattern."""
    conn = get_connection()
    init_schema(conn)
    rows = conn.execute(
        """SELECT postings.id, companies.name, postings.title, postings.url
           FROM postings JOIN companies ON postings.company_id = companies.id
           WHERE postings.status != 'stale'
           ORDER BY companies.name, postings.title"""
    ).fetchall()

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", kind="dead_link_check", total=len(rows), checked=0, dead=[], uncertain=[])
    thread = threading.Thread(target=_run_dead_link_check_job, args=(job_id, rows), daemon=True)
    thread.start()
    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/postings/dead-links/<job_id>")
def dead_links_results(job_id):
    """Results page for a finished check-dead-links job. Two tabs, plain
    show/hide via a few lines of inline JS (no new dependency, matches
    this file's existing convention of server-rendered HTML + a small
    inline <script>, same as job_status_page):
      - 'Dead' -- confident 404/410 (or, for Workday postings, an empty
        jobPostingInfo -- see _check_workday_url_alive()) hits. Each has
        a checkbox (checked by default) and submits to mark_stale_route.
      - 'Inconclusive' -- everything check_url_alive() couldn't confirm
        either way (network errors, robots.txt blocks, non-404/410
        status codes). Read-only, no checkbox, no action -- surfaced so
        the 153/947 (16%) inconclusive rate from this feature's first
        real run isn't an invisible number with no detail behind it,
        NOT because these are safe to bulk-mark-stale; see
        check_url_alive()'s docstring for why that distinction matters.

    Also serves kind == "scout_and_check" jobs (the combined Scout +
    dead-link-check job) -- same job-dict fields (dead/uncertain/checked/
    total), so this page needed no other changes to support it.
    """
    job = _get_job(job_id)
    if job is None or job.get("kind") not in ("dead_link_check", "scout_and_check"):
        abort(404)
    if job.get("status") not in ("done", "cancelled", "interrupted"):
        return redirect(url_for("job_status_page", job_id=job_id))

    dead = job.get("dead", [])
    uncertain = job.get("uncertain", [])

    # Re-check CURRENT status against the DB, not just what the sweep saw
    # -- added after a real session where submitting the mark-stale form
    # redirected back here looking IDENTICAL to before submitting (this
    # page was rendering the job's in-memory snapshot from before the
    # write, with no way to tell the write had happened). Entries already
    # marked stale since this job ran show as done, not as if nothing
    # happened.
    already_stale_ids: set[int] = set()
    if dead:
        conn = get_connection()
        init_schema(conn)
        placeholders = ",".join("?" for _ in dead)
        rows = conn.execute(
            f"SELECT id FROM postings WHERE status = 'stale' AND id IN ({placeholders})",
            tuple(d["id"] for d in dead),
        ).fetchall()
        already_stale_ids = {r[0] for r in rows}

    marked_param = request.args.get("marked")
    banner_html = ""
    if marked_param is not None:
        try:
            marked_n = int(marked_param)
        except ValueError:
            marked_n = 0
        banner_html = (
            f'<div class="empty-state" style="margin-bottom:12px;">'
            f'Marked {marked_n} posting(s) as stale. '
            f'{len(already_stale_ids)} of {len(dead)} listed below are now confirmed stale in the database.</div>'
            if marked_n else ""
        )

    # Per-company breakdown, added after a real session where counting by
    # hand across a browser-history page turned out imprecise (23 vs 24,
    # etc.) -- Counter over the dead list, not a separate query, since
    # 'dead' already has every entry's company name sitting in memory.
    company_counts = collections.Counter(d["company"] for d in dead)
    company_breakdown_html = "".join(
        f'<div class="card__meta">{_esc(company)}: {count}</div>'
        for company, count in sorted(company_counts.items(), key=lambda kv: -kv[1])
    ) or '<div class="card__meta">(none)</div>'

    def _entry_card(d: dict, with_checkbox: bool) -> str:
        is_done = d["id"] in already_stale_ids
        if is_done:
            checkbox_html = '<div class="card__meta" style="font-weight:600;">&#10003; Marked stale</div>'
        elif with_checkbox:
            checkbox_html = f'<div class="checkbox-field"><input type="checkbox" name="posting_id" value="{d["id"]}" checked></div>'
        else:
            checkbox_html = ""
        return f"""<div class="card">
  {checkbox_html}
  <div>
    <div class="card__company">{_esc(d['company'])}</div>
    <h3 class="card__title">{_esc(d['title'])}</h3>
    <div class="card__meta">{_esc(d['detail'])} &middot; <a href="{_esc(d['url'])}" target="_blank">original posting</a></div>
  </div>
</div>"""

    dead_html = "".join(_entry_card(d, with_checkbox=True) for d in dead) or \
        '<div class="empty-state">No confident dead links.</div>'
    uncertain_html = "".join(_entry_card(d, with_checkbox=False) for d in uncertain) or \
        '<div class="empty-state">Nothing inconclusive.</div>'

    dead_tab_body = f"""<form method="post" action="{url_for('mark_stale_route')}">
    <input type="hidden" name="redirect_to" value="{url_for('dead_links_results', job_id=job_id)}">
    <p class="sub">Uncheck any you don't want marked, then confirm -- nothing is written until you submit.</p>
    <div class="card" style="margin-bottom:12px;"><div class="card__company">By company</div>{company_breakdown_html}</div>
    <div class="grid">{dead_html}</div>
    {f'''<div class="btn-row" style="margin-top:16px;">
      <button class="btn" type="submit">Mark checked posting(s) as stale</button>
    </div>''' if dead else ""}
  </form>""" if dead else f'<div class="grid">{dead_html}</div>'

    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Dead link check</h1></div>
  {banner_html}
  <p class="sub">Checked {job.get('checked', 0)} posting(s) &middot; {len(dead)} confident dead link(s)
  &middot; {len(uncertain)} inconclusive.</p>
  <div class="tab-row" style="margin-bottom:12px;">
    <button class="btn btn--small" id="tab-btn-dead" onclick="showTab('dead')">Dead ({len(dead)})</button>
    <button class="btn btn--small btn--secondary" id="tab-btn-uncertain" onclick="showTab('uncertain')">Inconclusive ({len(uncertain)})</button>
  </div>
  <div id="tab-dead">{dead_tab_body}</div>
  <div id="tab-uncertain" style="display:none;">
    <p class="sub">Not treated as dead -- network errors, robots.txt blocks, or a status code that doesn't confidently mean "gone" (see check_url_alive() for the reasoning). No action available here on purpose.</p>
    <div class="grid">{uncertain_html}</div>
  </div>
  <p class="sub" style="margin-top:16px;"><a class="btn btn--secondary btn--small" href="{url_for('index')}">Back to postings</a></p>
</div>
<script>
function showTab(name) {{
  document.getElementById('tab-dead').style.display = name === 'dead' ? '' : 'none';
  document.getElementById('tab-uncertain').style.display = name === 'uncertain' ? '' : 'none';
  document.getElementById('tab-btn-dead').className = name === 'dead' ? 'btn btn--small' : 'btn btn--small btn--secondary';
  document.getElementById('tab-btn-uncertain').className = name === 'uncertain' ? 'btn btn--small' : 'btn btn--small btn--secondary';
}}
</script>"""
    return _page("Dead link check", body)


@app.route("/postings/mark-stale", methods=["POST"])
def mark_stale_route():
    """The only route that actually writes status='stale' from this
    feature -- called either from dead_links_results()'s bulk-confirm
    form (posting_id appears once per checked box) or from the
    single-posting 'Mark as stale' button on posting_detail() (a lone
    posting_id). Never called automatically -- see _run_dead_link_check_job's
    docstring for why a detected dead link is a candidate, not a write,
    until a person submits this form.

    Appends ?marked=<count> onto the redirect -- added after a real
    session where submitting this form redirected back to
    dead_links_results() with NO visible change (that page re-renders
    from the job's in-memory snapshot taken BEFORE this write, so it
    looked identical whether the write succeeded or silently failed).
    dead_links_results() reads this param to show an explicit
    confirmation banner instead of leaving the person to go check the
    DB by hand to find out.
    """
    posting_ids = [int(pid) for pid in request.form.getlist("posting_id")]
    marked_count = 0
    if posting_ids:
        conn = get_connection()
        init_schema(conn)
        conn.executemany(
            # COALESCE so re-confirming an already-stale posting (e.g. it
            # shows up in a later dead-link sweep before a repost lands)
            # doesn't reset the clock repost-turnaround-time is measured
            # from -- stale_at is meant to be set exactly once.
            "UPDATE postings SET status = 'stale', stale_at = COALESCE(stale_at, datetime('now')) WHERE id = ?",
            [(pid,) for pid in posting_ids],
        )
        conn.commit()
        marked_count = len(posting_ids)
    redirect_to = request.form.get("redirect_to") or url_for("index")
    separator = "&" if "?" in redirect_to else "?"
    return redirect(f"{redirect_to}{separator}marked={marked_count}")


@app.route("/postings/delete", methods=["POST"])
def delete_posting_route():
    """Permanently removes a posting -- unlike mark_stale_route, this is
    not reversible and the row is actually gone, not just hidden from the
    normal list. Added 2026-08-17 alongside the browser extension capture
    work: capture's dedup check matches on (company_id, url) regardless
    of status, so a posting mistakenly marked stale (e.g. while testing
    the extension) could never be re-captured under the same URL --
    mark-stale alone had no way to undo that. Before this route existed,
    the only way to actually delete a row was a standalone one-off script
    run directly against the database from the terminal
    (delete_posting.py); this is the same delete logic, exposed as a
    dashboard button instead.

    schema.sql has no ON DELETE CASCADE on any of postings' referencing
    foreign keys, so dependent rows (drafts, applications, outreach_emails)
    are deleted explicitly first, and any OTHER posting's
    reposted_from_id pointing at this one is cleared -- otherwise either
    the delete would fail outright (FK enforcement) or leave a dangling
    reference (if not enforced), matching the same cleanup order
    delete_posting.py already used.

    Single posting_id only (unlike mark_stale_route, which accepts a
    list) -- there's no bulk-delete UI today, only the single button on
    posting_detail(). Extend to getlist("posting_id") the same way if a
    bulk version is ever needed.
    """
    posting_id = request.form.get("posting_id")
    if not posting_id:
        abort(400)
    posting_id = int(posting_id)

    conn = get_connection()
    init_schema(conn)

    existing = conn.execute("SELECT id FROM postings WHERE id = ?", (posting_id,)).fetchone()
    if existing is not None:
        conn.execute("DELETE FROM drafts WHERE posting_id = ?", (posting_id,))
        conn.execute("DELETE FROM applications WHERE posting_id = ?", (posting_id,))
        conn.execute("DELETE FROM outreach_emails WHERE posting_id = ?", (posting_id,))
        conn.execute(
            "UPDATE postings SET reposted_from_id = NULL WHERE reposted_from_id = ?",
            (posting_id,),
        )
        conn.execute("DELETE FROM postings WHERE id = ?", (posting_id,))
        conn.commit()

    redirect_to = request.form.get("redirect_to") or url_for("index")
    separator = "&" if "?" in redirect_to else "?"
    return redirect(f"{redirect_to}{separator}deleted={1 if existing is not None else 0}")


@app.route("/jobs/<job_id>")
def job_status_page(job_id):
    job = _get_job(job_id)
    if job is None:
        abort(404)

    if job.get("kind") == "batch_generate":
        # Dedicated rendering, not the generic spinner-wrap template below --
        # this is the one job kind the user explicitly asked to see two REAL
        # progress bars for (outer: which posting; inner: that posting's own
        # step/total_steps, same contract _run_generation() uses for the
        # single-posting case), plus a running results list as each posting
        # finishes -- not just a final summary line.
        total = job.get("total") or 0
        batch_index = job.get("batch_index") or 0
        step = job.get("step") or 0
        total_steps = job.get("total_steps") or 0
        cancel_form = ""
        if job.get("status") in ("queued", "running"):
            cancel_form = f"""<form method="post" action="{url_for('cancel_job_route', job_id=job_id)}" id="batch-cancel-form"
  style="margin-bottom:14px;"
  onsubmit="return confirm('Cancel this batch? It stops after the current posting finishes, not instantly.');">
  <input type="hidden" name="redirect_to" value="{url_for('job_status_page', job_id=job_id)}">
  <button class="btn btn--secondary btn--small" type="submit" style="color:#b00020;border-color:#b00020;">Cancel batch</button>
</form>"""
        body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Batch generation</h1></div>
  {cancel_form}
  <div class="progress-panel">
    <p style="font-weight:600;margin:0 0 6px;">Posting <span id="batch-idx">{batch_index}</span> of <span id="batch-total">{total}</span></p>
    <progress id="batch-progress" value="{batch_index}" max="{total or 1}" style="width:100%;height:10px;"></progress>
    <p id="batch-current" class="sub" style="margin-top:6px;"></p>
  </div>
  <div class="progress-panel" style="margin-top:16px;">
    <p style="font-weight:600;margin:0 0 6px;">Current posting</p>
    <progress id="item-progress" value="{step}" max="{total_steps or 1}" style="width:100%;height:10px;"></progress>
    <p id="item-current" class="sub" style="margin-top:6px;"></p>
  </div>
  <div id="batch-results" style="margin-top:20px;"></div>
  <p id="batch-done-line" style="margin-top:16px;"></p>
</div>
<script>
async function pollBatch() {{
  const r = await fetch("{url_for('job_status_json', job_id=job_id)}");
  if (!r.ok) {{ setTimeout(pollBatch, 2500); return; }}
  const j = await r.json();

  document.getElementById("batch-idx").textContent = j.batch_index || 0;
  document.getElementById("batch-total").textContent = j.total || 0;
  const batchBar = document.getElementById("batch-progress");
  if (batchBar) {{ batchBar.max = j.total || 1; batchBar.value = j.batch_index || 0; }}
  document.getElementById("batch-current").textContent =
    j.current_company ? (j.current_company + (j.current_title ? " \\u2014 " + j.current_title : "")) : "";

  const itemBar = document.getElementById("item-progress");
  if (itemBar && j.total_steps) {{ itemBar.max = j.total_steps; itemBar.value = j.step || 0; }}
  document.getElementById("item-current").textContent =
    (j.current || "working\\u2026") + (j.total_steps ? " (" + (j.step || 0) + "/" + j.total_steps + ")" : "");

  const results = j.results || [];
  const resultsEl = document.getElementById("batch-results");
  if (results.length) {{
    resultsEl.innerHTML = "<p style='font-weight:600;margin:0 0 6px;'>Completed so far</p>" +
      results.map(function(r) {{
        return r.status === "done"
          ? '<div class="sub">\\u2713 ' + r.company + ' \\u2014 ' + r.title + '</div>'
          : '<div class="sub" style="color:#b00020;">\\u2717 ' + r.company + ' \\u2014 ' + r.title + ': ' + r.error + '</div>';
      }}).join("");
  }}

  if (j.status === "done" || j.status === "cancelled" || j.status === "interrupted") {{
    const cancelForm = document.getElementById("batch-cancel-form");
    if (cancelForm) cancelForm.style.display = "none";
    let prefix = "<strong>Done.</strong> ";
    if (j.status === "cancelled") prefix = "<strong>Cancelled.</strong> ";
    if (j.status === "interrupted") prefix = "<strong>Interrupted by a dashboard restart.</strong> ";
    document.getElementById("batch-done-line").innerHTML =
      prefix + (j.succeeded || 0) + " succeeded, " + (j.failed || 0) + " failed" +
      ((j.status === "cancelled" || j.status === "interrupted") ? ", " + ((j.total || 0) - ((j.results || []).length)) + " not run" : "") + ". " +
      '<a class="btn btn--small" href="{url_for("index")}">Back to postings</a>';
    return;
  }} else if (j.status === "error") {{
    document.getElementById("batch-done-line").textContent = "Batch failed: " + j.error;
    return;
  }}
  setTimeout(pollBatch, 2000);
}}
pollBatch();
</script>"""
        return _page("Batch generation", body)

    body = f"""<div class="dash-wrap"><div class="spinner-wrap">
  <div class="spinner"></div>
  <p id="status">Starting…</p>
  <p id="detail" style="font-size:13px;color:var(--ink-faint);"></p>
  <progress id="generic-progress" value="0" max="1" style="width:100%;height:8px;margin-top:10px;display:none;"></progress>
  <p id="done-link"></p>
  <div id="cancel-wrap">{
    f'''<form method="post" action="{url_for("cancel_job_route", job_id=job_id)}" id="generic-cancel-form"
  style="margin-top:12px;" onsubmit="return confirm('Cancel this job? It stops after the current item finishes, not instantly.');">
  <input type="hidden" name="redirect_to" value="{url_for("job_status_page", job_id=job_id)}">
  <button class="btn btn--secondary btn--small" type="submit" style="color:#b00020;border-color:#b00020;">Cancel</button></form>'''
    if job.get("kind") in ("batch_generate", "score_batch", "dead_link_check", "scout", "generate", "scout_and_check")
    and job.get("status") in ("queued", "running") else ""
  }</div>
</div></div>
<script>
async function poll() {{
  const r = await fetch("{url_for('job_status_json', job_id=job_id)}");
  const j = await r.json();
  const el = document.getElementById("status");
  const detailEl = document.getElementById("detail");
  const linkEl = document.getElementById("done-link");
  const cancelForm = document.getElementById("generic-cancel-form");
  const bar = document.getElementById("generic-progress");

  // Unified progress-bar contract (Captain roadmap #3): ONE line here
  // sets the bar for every job kind, reading the same progress_fraction
  // field job_status_json() computes server-side via
  // _job_progress_fraction() -- no per-kind bar logic duplicated in JS.
  if (bar && j.status !== "done" && typeof j.progress_fraction === "number") {{
    bar.style.display = "";
    bar.value = j.progress_fraction;
  }}

  if (j.status === "done" || j.status === "cancelled" || j.status === "interrupted") {{
    if (cancelForm) cancelForm.style.display = "none";
    if (bar) bar.style.display = "none";
    let cancelledPrefix = "";
    if (j.status === "cancelled") cancelledPrefix = "Cancelled. ";
    if (j.status === "interrupted") cancelledPrefix = "Interrupted by a dashboard restart. ";
    if (j.status === "done" && j.kind === "generate") {{
      window.location = "/postings/" + j.posting_id;
      return;
    }}
    if (j.kind === "dead_link_check" || j.kind === "scout_and_check") {{
      window.location = "{url_for('dead_links_results', job_id=job_id)}";
      return;
    }}
    if (j.kind === "score_batch") {{
      el.textContent = cancelledPrefix + "Done.";
      detailEl.textContent = `Scored ${{j.scored}}, skipped ${{j.skipped}}, of ${{j.total}} filtered posting(s).`;
    }} else if (j.kind === "scout") {{
      el.textContent = cancelledPrefix + "Done.";
      detailEl.textContent = `${{j.companies_checked}} companies checked, ${{j.new_postings}} new posting(s)` +
        (j.error_count ? `, ${{j.error_count}} error(s) -- see run_log for detail.` : ".");
    }} else if (j.kind === "generate" && (j.status === "cancelled" || j.status === "interrupted")) {{
      el.textContent = cancelledPrefix + "No draft was saved.";
      linkEl.innerHTML = j.posting_id
        ? '<a class="btn btn--small" href="/postings/' + j.posting_id + '">Back to posting</a>'
        : '<a class="btn btn--small" href="{url_for("index")}">Back to postings</a>';
      return;
    }} else {{
      el.textContent = cancelledPrefix + "Done.";
    }}
    linkEl.innerHTML = '<a class="btn btn--small" href="{url_for("index")}">View postings</a>';
    return;
  }} else if (j.status === "error") {{
    if (cancelForm) cancelForm.style.display = "none";
    if (bar) bar.style.display = "none";
    el.textContent = "Failed: " + j.error;
    return;
  }} else if (j.kind === "score_batch") {{
    el.textContent = j.status === "running" ? "Scoring\\u2026" : "Queued\\u2026";
    detailEl.textContent = `${{j.scored || 0}} scored, ${{j.skipped || 0}} skipped, of ${{j.total}} filtered posting(s)` +
      (j.current ? ` \\u2014 currently: ${{j.current}}` : "");
    setTimeout(poll, 2000);
  }} else if (j.kind === "scout") {{
    el.textContent = j.status === "running" ? "Running Scout\\u2026" : "Queued\\u2026";
    detailEl.textContent = j.total_companies
      ? `${{j.companies_done || 0}} of ${{j.total_companies}} companies checked` +
        (j.current_company ? ` \\u2014 last: ${{j.current_company}}` : "")
      : "Checking company career pages\\u2026";
    setTimeout(poll, 2500);
  }} else if (j.kind === "dead_link_check") {{
    el.textContent = j.status === "running" ? "Checking posting links\\u2026" : "Queued\\u2026";
    detailEl.textContent = `${{j.checked || 0}} of ${{j.total}} posting(s) checked` +
      (j.dead && j.dead.length ? `, ${{j.dead.length}} dead link(s) found so far` : "") +
      (j.current ? ` \\u2014 currently: ${{j.current}}` : "");
    setTimeout(poll, 2000);
  }} else if (j.kind === "scout_and_check") {{
    if (j.phase === "dead_link_check") {{
      el.textContent = j.status === "running" ? "Checking posting links\\u2026" : "Queued\\u2026";
      detailEl.textContent = `Scout done: ${{j.companies_checked || 0}} companies, ${{j.new_postings || 0}} new. ` +
        `Checking links: ${{j.checked || 0}} of ${{j.total}} checked` +
        (j.dead && j.dead.length ? `, ${{j.dead.length}} dead link(s) found so far` : "") +
        (j.current ? ` \\u2014 currently: ${{j.current}}` : "");
    }} else {{
      el.textContent = j.status === "running" ? "Running Scout\\u2026" : "Queued\\u2026";
      detailEl.textContent = j.total_companies
        ? `Scouting: ${{j.companies_done || 0}} of ${{j.total_companies}} companies checked` +
          (j.current_company ? ` \\u2014 last: ${{j.current_company}}` : "")
        : "Checking company career pages\\u2026";
    }}
    setTimeout(poll, 2500);
  }} else {{
    el.textContent = j.status === "running" ? "Running Writer \\u2192 Critic \\u2192 Revision\\u2026 (a few minutes on local models)" : "Queued\\u2026";
    detailEl.textContent = j.total_steps
      ? `${{j.current || "working"}} (step ${{j.step || 0}} of ${{j.total_steps}})`
      : "";
    setTimeout(poll, 2500);
  }}
}}
poll();
</script>"""
    return _page("Job status", body)


@app.route("/jobs/<job_id>.json")
def job_status_json(job_id):
    job = _get_job(job_id)
    if job is None:
        abort(404)
    # progress_fraction is computed fresh on every read, not stored --
    # same "single source of truth" reasoning as _job_display(): the
    # underlying fields (step/total_steps, checked/total, etc.) are the
    # real state, this is just a derived view of it. See
    # _job_progress_fraction()'s docstring for the unified-progress-bar
    # contract this is part of.
    return {**job, "progress_fraction": _job_progress_fraction(job)}


@app.route("/postings/<int:posting_id>/report")
def posting_report(posting_id):
    conn = get_connection()
    init_schema(conn)
    posting = _get_posting(conn, posting_id)
    if posting is None:
        abort(404)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)

    round_diffs = diff_revision_result(draft.result)
    html_out = render_posting_report(
        draft.result,
        company_name=posting["company"],
        job_title=posting["title"],
        job_description=posting["description"] or "",
        round_diffs=round_diffs,
        dashboard_url=url_for("posting_detail", posting_id=posting_id, _external=True),
    )
    return Response(html_out, mimetype="text/html")


def _display_draft(draft: "drafts_db.DraftRecord", edit: dict | None):
    """Returns the WriterDraft to render for preview/export -- the active
    hand edit's summary/bullets/cover letter merged onto the AI draft's
    own company_name/job_title/cover_letter_blocks, or the AI draft
    unchanged if there's no active final_edit row. Both the preview
    routes (raw HTML) and the export routes (PDF) call this same
    function, so they're always showing/downloading identical content
    -- see final_edit's schema.sql comment and this file's Writer/export
    roadmap item.
    """
    if edit is None:
        return draft.result.final_draft
    return dataclasses.replace(
        draft.result.final_draft,
        tailored_summary=edit["tailored_summary"] or "",
        tailored_bullets=edit["tailored_bullets"] or "",
        cover_letter=edit["cover_letter"] or "",
    )


@app.route("/postings/<int:posting_id>/resume/preview")
def posting_resume_preview(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    edit = drafts_db.get_final_edit(conn, posting_id)
    settings = settings_db.get_candidate_settings(conn)
    html_out = render_resume_html(
        _display_draft(draft, edit),
        candidate_name=settings.candidate_name,
        contact_line=settings.contact_line,
    )
    return Response(html_out, mimetype="text/html")


@app.route("/postings/<int:posting_id>/resume.pdf")
def posting_resume_pdf(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    edit = drafts_db.get_final_edit(conn, posting_id)
    settings = settings_db.get_candidate_settings(conn)
    html_out = render_resume_html(
        _display_draft(draft, edit),
        candidate_name=settings.candidate_name,
        contact_line=settings.contact_line,
    )
    pdf_bytes = html_to_pdf_bytes(html_out)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume_posting_{posting_id}.pdf"'},
    )


@app.route("/postings/<int:posting_id>/cover-letter/preview")
def posting_cover_letter_preview(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    edit = drafts_db.get_final_edit(conn, posting_id)
    settings = settings_db.get_candidate_settings(conn)
    html_out = render_cover_letter_html(
        _display_draft(draft, edit),
        candidate_name=settings.candidate_name,
        contact_line=settings.contact_line,
    )
    return Response(html_out, mimetype="text/html")


@app.route("/postings/<int:posting_id>/cover-letter.pdf")
def posting_cover_letter_pdf(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    edit = drafts_db.get_final_edit(conn, posting_id)
    settings = settings_db.get_candidate_settings(conn)
    html_out = render_cover_letter_html(
        _display_draft(draft, edit),
        candidate_name=settings.candidate_name,
        contact_line=settings.contact_line,
    )
    pdf_bytes = html_to_pdf_bytes(html_out)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="cover_letter_posting_{posting_id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Manual posting entry -- for a posting Scout didn't find on its own
# (the 2026-08-09 handoff's concrete example: repeatedly hand-testing the
# same Guardant Health posting via --job-description-file on the CLI
# instead of having it live in the dashboard like everything else).
#
# _find_or_create_company_light() is deliberately NOT
# detector.py's _get_or_create_company_id(): that function takes a full
# CompanyConfig (ats_type/ats_slug/css_selector, sourced from
# companies.yaml) which a manually-typed company name doesn't have. This
# is the lighter-weight version the handoff called for -- name only,
# everything else NULL, same as any company that would otherwise need a
# companies.yaml entry to exist at all.
#
# careers_url is NOT NULL in schema.sql with no default, so a manually-
# created company needs SOME value there. Using the posting's own URL as
# a stand-in (rather than fabricating a guessed careers-page URL, which
# would look like real data but not be) is the honest choice -- flagged
# here rather than silently picked.
# ---------------------------------------------------------------------------


def _find_or_create_company_light(conn, name: str, fallback_url: str) -> int:
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO companies (name, careers_url) VALUES (?, ?)",
        (name, fallback_url),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Shared manual-posting-creation logic, factored out 2026-08-16 so the
# existing HTML form route (posting_manual_create, unchanged in behavior)
# and the new JSON capture route (api_postings_capture, for the planned
# browser extension) share one insert/dedup implementation rather than two
# copies that could silently drift apart. Same dedup semantics as Scout's
# own _upsert_postings() (re-sighting an existing (company_id, url) pair
# is a no-op, not an error), same company-fallback rule as before
# (careers_url defaults to the posting's own URL, never a guessed one).
# ---------------------------------------------------------------------------


def _create_manual_posting(
    conn,
    *,
    company_name: str,
    title: str,
    url: str,
    location: str | None,
    description: str,
    apply_url: str | None = None,
) -> tuple[str, int]:
    """Create (or find) a manually-captured posting.

    apply_url is the direct link to actually apply for THIS specific
    posting -- e.g. LinkedIn shows an "apply on company site" link
    distinct from the LinkedIn job URL itself, and that's genuinely the
    more important link since it's what someone clicks to apply, not the
    LinkedIn page url stores for dedup purposes. Stored on the posting
    itself (postings.apply_url) and rendered on its detail page.

    Secondarily, when a NEW company row is being created and apply_url is
    provided, it's also used as that company's careers_url fallback
    (better than the LinkedIn url as a stand-in). Has no effect when the
    company already exists -- an existing company's careers_url is never
    silently overwritten by a later capture, since a wrong/stale link
    typed into one job's capture shouldn't clobber a value Scout may
    already depend on.

    Returns (status, posting_id) where status is "created" if a new row
    was inserted, or "duplicate" if a posting with this (company, url)
    already existed -- caller decides how to present either case.
    """
    fallback = apply_url.strip() if apply_url and apply_url.strip() else url
    company_id = _find_or_create_company_light(conn, company_name, fallback_url=fallback)

    existing = conn.execute(
        "SELECT id FROM postings WHERE company_id = ? AND url = ?", (company_id, url)
    ).fetchone()
    if existing:
        return "duplicate", existing[0]

    cur = conn.execute(
        """INSERT INTO postings (company_id, title, url, apply_url, location, description, status)
           VALUES (?, ?, ?, ?, ?, ?, 'new')""",
        (company_id, title, url, (apply_url or None), location, description),
    )
    conn.commit()
    return "created", cur.lastrowid


@app.route("/postings/manual")
def posting_manual_form():
    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Add a posting manually</h1>
    <p class="sub">For anything Scout didn't find on its own. Once added, it behaves exactly
    like any Scout-found posting -- same Generate button, same report, same PDFs.</p></div>
  <form method="post" action="{url_for('posting_manual_create')}">
    <div class="form-row"><label style="width:100%;">Company name
      <input class="wide" type="text" name="company" required></label></div>
    <div class="form-row"><label style="width:100%;">Job title
      <input class="wide" type="text" name="title" required></label></div>
    <div class="form-row"><label style="width:100%;">Posting URL
      <input class="wide" type="text" name="url" required placeholder="https://..."></label></div>
    <div class="form-row"><label style="width:100%;">Location (optional)
      <input class="wide" type="text" name="location" placeholder="e.g. South San Francisco, CA"></label></div>
    <div class="form-row" style="display:block;"><label>Job description</label>
      <textarea class="manual-jd" name="description" required></textarea></div>
    <div class="btn-row">
      <button class="btn" type="submit">Add posting</button>
      <a class="btn btn--secondary" href="{url_for('index')}">Cancel</a>
    </div>
  </form>
</div>"""
    return _page("Add posting manually", body)


@app.route("/postings/manual", methods=["POST"])
def posting_manual_create():
    conn = get_connection()
    init_schema(conn)

    company_name = (request.form.get("company") or "").strip()
    title = (request.form.get("title") or "").strip()
    url = (request.form.get("url") or "").strip()
    location = (request.form.get("location") or "").strip() or None
    description = (request.form.get("description") or "").strip()

    if not (company_name and title and url and description):
        body = '<div class="dash-wrap"><p>Company, title, URL, and job description are all required.</p></div>'
        return _page("Error", body), 400

    # status is "created" or "duplicate" -- the HTML form route doesn't
    # need to distinguish them in its response, same behavior as before
    # this was factored out: either way, land on that posting's page.
    _status, posting_id = _create_manual_posting(
        conn,
        company_name=company_name,
        title=title,
        url=url,
        location=location,
        description=description,
    )
    return redirect(url_for("posting_detail", posting_id=posting_id))


# ---------------------------------------------------------------------------
# JSON capture endpoint for the planned browser extension (see
# docs/ROADMAP.md's "Browser extension capture" item). Same underlying
# _create_manual_posting() as the HTML form above -- this route only
# differs in speaking JSON in and out instead of an HTML form/redirect,
# since an extension's background script needs a machine-readable result
# (posting_id + a URL to open), not a page to parse.
#
# No new auth here: this project's whole dashboard is already documented
# as no-auth/localhost-only by design (see this module's top docstring),
# and an extension's background service worker reaching 127.0.0.1 is the
# same "something running on your own machine" case that model already
# covers -- not a new exposure. If the dashboard is ever bound to
# something other than localhost, this endpoint (and the rest of the
# dashboard) would need real auth added, but that's an existing project-
# wide gap, not specific to this route.
# ---------------------------------------------------------------------------


@app.route("/api/postings/capture", methods=["POST"])
def api_postings_capture():
    conn = get_connection()
    init_schema(conn)

    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"status": "error", "error": "Request body must be JSON."}), 400

    company_name = (payload.get("company") or "").strip()
    title = (payload.get("title") or "").strip()
    url = (payload.get("url") or "").strip()
    location = (payload.get("location") or "").strip() or None
    description = (payload.get("description") or "").strip()
    apply_url = (payload.get("apply_url") or "").strip() or None

    if not (company_name and title and url and description):
        return (
            jsonify(
                {
                    "status": "error",
                    "error": "company, title, url, and description are all required.",
                }
            ),
            400,
        )

    status, posting_id = _create_manual_posting(
        conn,
        company_name=company_name,
        title=title,
        url=url,
        location=location,
        description=description,
        apply_url=apply_url,
    )
    return jsonify(
        {
            "status": status,
            "posting_id": posting_id,
            "dashboard_url": url_for("posting_detail", posting_id=posting_id),
        }
    )


# ---------------------------------------------------------------------------
# Candidate settings -- name/contact line for the PDF header
# (resume_pdf.py's candidate_name/contact_line params, previously never
# wired to anything -- see the 2026-08-13 handoff). A dashboard settings
# page rather than a config/*.yaml file so it's editable without a
# restart (see settings_db.py's module docstring for the reasoning).
# ---------------------------------------------------------------------------


@app.route("/settings")
def settings_page():
    conn = get_connection()
    init_schema(conn)
    settings = settings_db.get_candidate_settings(conn)
    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Settings</h1>
    <p class="sub">Your name and contact line, used only for the resume/cover-letter
    PDF header (resume_pdf.py) -- nothing else in BioHunter reads this.</p></div>
  <form method="post" action="{url_for('settings_save')}">
    <div class="form-row" style="display:block;"><label for="candidate_name">Full name</label>
      <input class="wide" type="text" id="candidate_name" name="candidate_name"
        value="{_esc(settings.candidate_name)}" placeholder="e.g. Jordan Rivera"></div>
    <div class="form-row" style="display:block;margin-top:14px;"><label for="contact_line">Contact line</label>
      <input class="wide" type="text" id="contact_line" name="contact_line"
        value="{_esc(settings.contact_line)}"
        placeholder="e.g. jordan@example.com &middot; (555) 123-4567 &middot; South San Francisco, CA"></div>
    <div class="btn-row" style="margin-top:20px;">
      <button class="btn" type="submit">Save</button>
      <a class="btn btn--secondary" href="{url_for('index')}">Cancel</a>
    </div>
  </form>
</div>"""
    return _page("Settings", body)


@app.route("/settings", methods=["POST"])
def settings_save():
    conn = get_connection()
    init_schema(conn)
    candidate_name = (request.form.get("candidate_name") or "").strip()
    contact_line = (request.form.get("contact_line") or "").strip()
    settings_db.save_candidate_settings(conn, candidate_name, contact_line)
    return redirect(url_for("settings_page"))


def _format_duration(seconds: float | None) -> str:
    """Renders a wall-clock duration as e.g. '4m 12s' or '1h 3m 0s'.
    None (no duration recorded -- run_log rows written before the
    2026-08-23 columns existed) renders as an em dash, not '0s'."""
    if seconds is None:
        return "\u2014"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


_TOKEN_RUN_KIND_LABELS = {
    "generate": "Generate",
    "batch_generate": "Batch generate",
    "score_batch": "Score batch",
}


def _token_run_results_html(kind: str, job_data: dict | None) -> str:
    """Renders the 'Results' cell for one run_log row, reading from the
    matching `jobs` table row's data_json (job_data -- already parsed,
    None if that job was since cleared via 'Clear finished jobs' or
    predates persisted job history). Deliberately reuses data this file
    already stores rather than duplicating result details into run_log
    itself -- see schema.sql's comment on run_log.job_id.

    score_batch has no per-posting link list: a real run can touch
    hundreds of postings (389 in the run that prompted this feature),
    and _run_score_batch() only ever tracked aggregate scored/skipped
    counts, not individual posting ids -- adding that would mean
    re-serializing a growing list on every single posting during a
    large batch, a real cost for a rarely-needed list. A link to the
    postings index is the practical middle ground.
    """
    faint = '<span style="color:var(--ink-faint)">\u2014</span>'
    if job_data is None:
        return faint

    if kind == "generate":
        posting_id = job_data.get("posting_id")
        company = job_data.get("company_name") or "?"
        title = job_data.get("job_title") or "?"
        label = f"{_esc(company)} \u2014 {_esc(title)}"
        if not posting_id:
            return label
        href = url_for("posting_detail", posting_id=posting_id)
        status = job_data.get("status")
        suffix = "" if status == "done" else f" ({_esc(status or '?')})"
        return f'<a href="{href}">{label}</a>{suffix}'

    if kind == "batch_generate":
        results = job_data.get("results") or []
        if not results:
            return faint
        succeeded = sum(1 for r in results if r.get("status") == "done")
        failed = len(results) - succeeded
        items = []
        for r in results:
            posting_id = r.get("posting_id")
            mark = "\u2713" if r.get("status") == "done" else "\u2717"
            label = f"{_esc(r.get('company') or '?')} \u2014 {_esc(r.get('title') or '?')}"
            if posting_id:
                href = url_for("posting_detail", posting_id=posting_id)
                items.append(f'<li><a href="{href}">{label}</a> {mark}</li>')
            else:
                items.append(f'<li>{label} {mark}</li>')
        summary = f"{succeeded} succeeded, {failed} failed ({len(results)} total)"
        return (
            f'<details class="result-links"><summary>{summary}</summary>'
            f'<ul style="margin:8px 0 0;padding-left:18px;">{"".join(items)}</ul></details>'
        )

    if kind == "score_batch":
        scored = job_data.get("scored", 0)
        skipped = job_data.get("skipped", 0)
        href = url_for("index")
        return f'{scored} scored, {skipped} skipped \u2014 <a href="{href}">view postings</a>'

    return faint


_MODEL_PRICING_PATH = "config/model_pricing.yaml"


def _load_model_pricing() -> dict:
    """Loads config/model_pricing.yaml for the /tokens cost calculator.
    Same relative-path convention llm.py's LLMClient uses for
    config/roles.yaml -- assumes the process is launched from the repo
    root, not resolved to an absolute path.

    Returns {} (not an exception) if the file is missing or malformed,
    so a dashboard restart never breaks over a config file the user
    hasn't created/edited yet -- the calculator section just renders
    with a "no pricing config found" note instead of 500ing the whole
    /tokens page. Loaded fresh on every request (not cached at module
    level) -- same posture as LLMClient's own roles.yaml loading, so
    editing this file and refreshing the page picks up changes without
    a process restart, unlike a .py edit.
    """
    try:
        with open(_MODEL_PRICING_PATH) as f:
            data = yaml.safe_load(f) or {}
        return data.get("models", {}), data.get("last_updated")
    except (OSError, yaml.YAMLError):
        logger.exception("failed to load %s -- /tokens calculator will show no pricing data", _MODEL_PRICING_PATH)
        return {}, None


def _token_cost_calculator_html(
    pricing: dict, pricing_updated: str | None, default_prompt: int, default_completion: int
) -> str:
    """Renders the /tokens cost calculator. Rebuilt 2026-08-24 from the
    original two-number-input version, per direct user feedback after
    seeing tokencalculator.ai:

    1. Models now group by `provider` (config/model_pricing.yaml's new
       field -- see that file's own comment) by default, instead of
       always being sorted cheapest-first, which scattered same-vendor
       models apart. A "Cheapest first" toggle switches back to cost
       sort for anyone who wants that view instead.
    2. Output tokens are now driven by a single "Input tokens" number
       plus an "Expected output size" percentage slider (0-300%) with
       tokencalculator.ai-style presets (Classification/RAG/Chat/Full
       response/Long generation), rather than a second raw number
       input the user has to fill in themselves. The percentage
       presets are approximate labels for common ratios, not a
       precise standard -- the slider itself is the source of truth,
       the buttons just jump it to a reasonable starting point.
    3. Clicking a Tokens value in the per-run table above (see
       tokens_dashboard()'s row loop) calls bhCalcFromRun(), which
       populates this calculator's input-tokens field and slider
       position from THAT run's actual prompt/completion split, then
       scrolls here -- so "what did this specific run cost elsewhere"
       is one click away.
    4. Clicking a model row here calls bhCalcAddColumn(), which adds
       (or removes, if clicking the same model again) a live cost
       column to the per-run table using that model's rate against
       each row's OWN actual prompt/completion tokens (read from the
       data-prompt/data-completion attributes tokens_dashboard()'s row
       loop puts on every <tr>) -- not this calculator's hypothetical
       input-tokens value, which only feeds the calculator table
       itself.

    Still entirely client-side (see prior version's docstring for why:
    small pricing table, embedded as JSON, no round trip needed).

    Returns a message instead of a calculator if config/model_pricing.yaml
    failed to load or is empty.
    """
    if not pricing:
        return f"""<h2 style="margin-top:32px;">Cost calculator</h2>
<p class="sub">No pricing data found at {html.escape(_MODEL_PRICING_PATH)} --
create that file (see the comment at the top of a fresh copy for the expected
format) to enable this calculator.</p>"""

    updated_note = f" · pricing last updated {html.escape(pricing_updated)}" if pricing_updated else ""
    pricing_json = json.dumps(pricing)

    default_pct = 5
    if default_prompt:
        default_pct = max(0, min(300, round(default_completion / default_prompt * 100)))

    return f"""<h2 style="margin-top:32px;">Cost calculator</h2>
<p class="sub">Manually-maintained reference pricing{updated_note} -- not a live feed;
verify against each provider's own pricing page before trusting this for a real
budgeting decision. Input tokens default to this dashboard's own lifetime total;
edit it, or adjust the output-size slider, to price a hypothetical volume instead.</p>

<div class="calc-inputs">
  <label>Input tokens
    <input type="number" id="calc-input-tokens" value="{default_prompt}" min="0" step="1">
  </label>
</div>

<div class="calc-output-size">
  <div class="calc-presets">
    <button type="button" class="calc-preset" data-pct="5">Classification</button>
    <button type="button" class="calc-preset" data-pct="25">RAG / Q&amp;A</button>
    <button type="button" class="calc-preset" data-pct="50">Chat</button>
    <button type="button" class="calc-preset" data-pct="100">Full response</button>
    <button type="button" class="calc-preset" data-pct="200">Long generation</button>
  </div>
  <input type="range" id="calc-pct" min="0" max="300" step="1" value="{default_pct}">
  <div class="calc-output-readout">
    <span id="calc-output-tokens">0</span> output tokens
    (<span id="calc-pct-readout">{default_pct}</span>% of input)
  </div>
</div>

<div class="calc-sort-toggle">
  <button type="button" id="calc-sort-provider" class="calc-sort-btn calc-sort-btn--active">By provider</button>
  <button type="button" id="calc-sort-cost" class="calc-sort-btn">Cheapest first</button>
</div>

<table id="calc-table">
  <tr><th>Model</th><th class="num">Input cost</th><th class="num">Output cost</th><th class="num">Total</th></tr>
</table>
<p class="sub">Click a model above to add its cost as a column to the Recent runs table.</p>

<script>
const bhModelPricing = {pricing_json};
let bhSortMode = "provider";
let bhActiveCostModel = null;

function bhFmtUsd(n) {{
  return "$" + n.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 4}});
}}

function bhCalcRows() {{
  const inputTokens = Math.max(0, Number(document.getElementById("calc-input-tokens").value) || 0);
  const pct = Math.max(0, Number(document.getElementById("calc-pct").value) || 0);
  const outputTokens = Math.round(inputTokens * pct / 100);
  document.getElementById("calc-pct-readout").textContent = pct;
  document.getElementById("calc-output-tokens").textContent = outputTokens.toLocaleString();
  return Object.entries(bhModelPricing).map(([name, p]) => {{
    const inputCost = (inputTokens / 1e6) * p.input_per_million;
    const outputCost = (outputTokens / 1e6) * p.output_per_million;
    return {{name, provider: p.provider || "", inputCost, outputCost, total: inputCost + outputCost}};
  }});
}}

function bhCalcRecalc() {{
  const rows = bhCalcRows();
  if (bhSortMode === "cost") {{
    rows.sort((a, b) => a.total - b.total);
  }} else {{
    rows.sort((a, b) => (a.provider + a.name).localeCompare(b.provider + b.name));
  }}
  const table = document.getElementById("calc-table");
  table.innerHTML = "<tr><th>Model</th><th class=\\"num\\">Input cost</th>" +
    "<th class=\\"num\\">Output cost</th><th class=\\"num\\">Total</th></tr>" +
    rows.map(r => {{
      const active = (r.name === bhActiveCostModel) ? " calc-row--active" : "";
      return "<tr class=\\"calc-row" + active + "\\" data-model=\\"" + r.name.replace(/"/g, "&quot;") + "\\">" +
        "<td>" + r.name + (r.provider ? " <span class=\\"calc-provider\\">(" + r.provider + ")</span>" : "") + "</td>" +
        "<td class=\\"num\\">" + bhFmtUsd(r.inputCost) + "</td>" +
        "<td class=\\"num\\">" + bhFmtUsd(r.outputCost) + "</td>" +
        "<td class=\\"num\\"><b>" + bhFmtUsd(r.total) + "</b></td></tr>";
    }}).join("");
  Array.from(table.querySelectorAll("tr.calc-row")).forEach(tr => {{
    tr.addEventListener("click", () => bhCalcAddColumn(tr.getAttribute("data-model")));
  }});
}}

function bhCalcFromRun(anchorEl) {{
  const tr = anchorEl.closest("tr.run-row");
  if (!tr) return;
  const prompt = Number(tr.getAttribute("data-prompt")) || 0;
  const completion = Number(tr.getAttribute("data-completion")) || 0;
  document.getElementById("calc-input-tokens").value = prompt;
  const pct = prompt ? Math.max(0, Math.min(300, Math.round(completion / prompt * 100))) : 0;
  document.getElementById("calc-pct").value = pct;
  bhCalcRecalc();
}}

function bhCalcAddColumn(modelName) {{
  const table = document.getElementById("run-table");
  if (!table) return;
  const headRow = table.rows[0];

  // Remove any existing dynamic cost column first -- only one shown at
  // a time, matching "click a model to add A column" (singular).
  const existingIdx = Array.from(headRow.cells).findIndex(c => c.classList.contains("dyn-cost"));
  if (existingIdx !== -1) {{
    for (const row of table.rows) {{ row.deleteCell(existingIdx); }}
  }}

  if (modelName === bhActiveCostModel) {{
    // Clicking the same model again just removes the column (toggle off).
    bhActiveCostModel = null;
    bhCalcRecalc();
    return;
  }}

  bhActiveCostModel = modelName;
  const p = bhModelPricing[modelName];
  const th = document.createElement("th");
  th.className = "dyn-cost num";
  th.textContent = modelName + " cost";
  headRow.appendChild(th);

  for (let i = 1; i < table.rows.length; i++) {{
    const row = table.rows[i];
    if (!row.classList.contains("run-row")) continue;  // skip if a non-data row ever appears
    const prompt = Number(row.getAttribute("data-prompt")) || 0;
    const completion = Number(row.getAttribute("data-completion")) || 0;
    const cost = (prompt / 1e6) * p.input_per_million + (completion / 1e6) * p.output_per_million;
    const td = document.createElement("td");
    td.className = "dyn-cost num";
    td.textContent = bhFmtUsd(cost);
    row.appendChild(td);
  }}
  bhCalcRecalc();
}}

document.getElementById("calc-input-tokens").addEventListener("input", bhCalcRecalc);
document.getElementById("calc-pct").addEventListener("input", bhCalcRecalc);
document.querySelectorAll(".calc-preset").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.getElementById("calc-pct").value = btn.getAttribute("data-pct");
    bhCalcRecalc();
  }});
}});
document.getElementById("calc-sort-provider").addEventListener("click", () => {{
  bhSortMode = "provider";
  document.getElementById("calc-sort-provider").classList.add("calc-sort-btn--active");
  document.getElementById("calc-sort-cost").classList.remove("calc-sort-btn--active");
  bhCalcRecalc();
}});
document.getElementById("calc-sort-cost").addEventListener("click", () => {{
  bhSortMode = "cost";
  document.getElementById("calc-sort-cost").classList.add("calc-sort-btn--active");
  document.getElementById("calc-sort-provider").classList.remove("calc-sort-btn--active");
  bhCalcRecalc();
}});
bhCalcRecalc();
</script>"""


@app.route("/tokens")
def tokens_dashboard():
    """Per-run token usage view (rebuilt 2026-08-23 from the original
    by-kind-only aggregate -- see schema.sql's comment on run_log's new
    columns for why a per-run view needed schema changes, not just a
    template change). Each row is one finished generate/batch_generate/
    score_batch job: date, duration (real wall-clock), tokens, avg
    tok/s (completion_tokens / llm_seconds -- same formula the live
    per-job progress badge uses elsewhere in this file, so the numbers
    agree), model, and a Results column linking back to what that run
    actually produced, read from the persisted `jobs` table via
    run_log.job_id.

    NEW 2026-08-23 (later same date): Model column added to the per-run
    table, plus a "By model" summary breaking down total tokens per
    distinct model -- both sourced from run_log.model (see
    _log_token_usage()'s docstring for how that column is populated;
    requires migrate_add_run_log_model.py to have been run against an
    existing database, since the column doesn't exist on one created
    before this addition). Rows logged before that migration show
    "(unknown model)" rather than being silently dropped, so historical
    totals stay visible, just unattributed.

    Capped at the 100 most recently finished runs -- no date-range
    filtering yet (same known gap as the original version had); the
    summary strip at the top is a real aggregate over the WHOLE table,
    not just the 100 shown, so cumulative totals stay accurate even
    once history grows past that cap.
    """
    conn = get_connection()
    init_schema(conn)

    total_row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(tokens_used), 0), "
        "COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(llm_seconds), 0) "
        "FROM run_log WHERE tokens_used IS NOT NULL"
    ).fetchone()
    total_runs, total_tokens, total_completion, total_llm_seconds = total_row
    overall_tok_s = f"{total_completion / total_llm_seconds:.0f}" if total_llm_seconds else "n/a"

    by_model_rows = conn.execute(
        "SELECT COALESCE(model, '(unknown model)'), COUNT(*), COALESCE(SUM(tokens_used), 0) "
        "FROM run_log WHERE tokens_used IS NOT NULL GROUP BY model ORDER BY 3 DESC"
    ).fetchall()

    rows = conn.execute(
        "SELECT agent, job_id, finished_at, duration_seconds, tokens_used, "
        "completion_tokens, llm_seconds, model "
        "FROM run_log WHERE tokens_used IS NOT NULL ORDER BY finished_at DESC LIMIT 100"
    ).fetchall()

    job_ids = [r[1] for r in rows if r[1]]
    jobs_by_id: dict[str, dict] = {}
    if job_ids:
        placeholders = ",".join("?" * len(job_ids))
        for jid, data_json in conn.execute(
            f"SELECT id, data_json FROM jobs WHERE id IN ({placeholders})", tuple(job_ids)
        ).fetchall():
            try:
                jobs_by_id[jid] = json.loads(data_json)
            except (TypeError, ValueError):
                pass  # malformed/legacy row -- results cell just shows the fallback dash

    if not rows:
        pricing, pricing_updated = _load_model_pricing()
        calculator_html = _token_cost_calculator_html(pricing, pricing_updated, default_prompt=0, default_completion=0)
        body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Token usage</h1></div>
  <p class="sub">No token usage logged yet -- run a generate, batch generate, or score batch job first.</p>
  {calculator_html}
</div>"""
        return _page("Token usage", body)

    row_html_parts = []
    for agent, job_id, finished_at, duration_seconds, tokens_used, completion_tokens, llm_seconds, model in rows:
        kind_label = _TOKEN_RUN_KIND_LABELS.get(agent, html.escape(agent))
        tok_s = f"{completion_tokens / llm_seconds:.0f}" if llm_seconds else "n/a"
        job_data = jobs_by_id.get(job_id)
        results_html = _token_run_results_html(agent, job_data)
        model_label = html.escape(model) if model else "(unknown model)"
        # prompt_tokens isn't selected separately above -- tokens_used is
        # always prompt+completion (see _log_token_usage()), so it's
        # recovered here rather than adding a column to the query.
        row_prompt_tokens = tokens_used - (completion_tokens or 0)
        row_html_parts.append(f"""<tr class="run-row" data-prompt="{row_prompt_tokens}" data-completion="{completion_tokens or 0}">
  <td>{_esc(finished_at or '')}</td>
  <td>{kind_label}</td>
  <td>{model_label}</td>
  <td class="num">{_format_duration(duration_seconds)}</td>
  <td class="num"><a href="#cost-calculator" class="run-tok-link" onclick="bhCalcFromRun(this)" title="Load this run's tokens into the cost calculator below">{tokens_used:,}</a></td>
  <td class="num">{tok_s}</td>
  <td>{results_html}</td>
</tr>""")

    cap_note = ""
    if total_runs > len(rows):
        cap_note = f'<p class="sub">Showing the {len(rows)} most recent of {total_runs} logged runs.</p>'

    table_html = f"""<table id="run-table">
  <tr><th>Date</th><th>Job kind</th><th>Model</th><th class="num">Duration</th><th class="num">Tokens</th>
      <th class="num">Avg tok/s</th><th>Results</th></tr>
  {''.join(row_html_parts)}
</table>
<p class="sub">Click a Tokens value to load that run into the calculator below. Click a model
in the calculator to add a per-run cost column here.</p>
{cap_note}"""

    by_model_html_rows = "".join(
        f"<tr><td>{html.escape(model)}</td><td>{runs}</td><td>{tokens:,}</td></tr>"
        for model, runs, tokens in by_model_rows
    )
    by_model_html = f"""<h2 style="margin-top:32px;">By model</h2>
<table>
  <tr><th>Model</th><th>Runs</th><th>Total tokens</th></tr>
  {by_model_html_rows}
</table>"""

    summary_html = f"""<div class="token-summary">
  <div class="stat"><span class="n">{total_runs}</span><span class="label">Runs logged</span></div>
  <div class="stat"><span class="n">{total_tokens:,}</span><span class="label">Total tokens</span></div>
  <div class="stat"><span class="n">{overall_tok_s}</span><span class="label">Overall avg tok/s</span></div>
</div>"""

    total_prompt, total_completion = conn.execute(
        "SELECT COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0) "
        "FROM run_log WHERE tokens_used IS NOT NULL"
    ).fetchone()
    pricing, pricing_updated = _load_model_pricing()
    calculator_html = _token_cost_calculator_html(
        pricing, pricing_updated, default_prompt=total_prompt, default_completion=total_completion
    )

    body = f"""<div class="dash-wrap dash-wrap--wide">
  <div class="detail-header"><h1>Token usage</h1>
    <p class="sub">Per-run token usage and generation speed. The cost calculator below
    is a separate, manually-priced reference table -- not tied to run_log.cost_usd,
    which stays unset since there's no live pricing feed this project pulls from.</p></div>
  {summary_html}
  {table_html}
  {by_model_html}
  <div id="cost-calculator">
  {calculator_html}
  </div>
</div>"""
    return _page("Token usage", body)


def main() -> None:
    parser = argparse.ArgumentParser(prog="biohunter-dashboard")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _load_jobs_from_db()
    # threaded=True: required -- the index/detail pages must stay
    # responsive to GET/poll requests while a background generation
    # thread is running, not just while Flask itself avoids blocking.
    app.run(port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
