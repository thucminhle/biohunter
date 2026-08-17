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
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import logging
import threading
import uuid

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
# In-memory job registry. See module docstring for why this is
# intentionally NOT a task queue -- single local user, a handful of
# concurrent generations at most, nothing here needs to survive a
# process restart (drafts_db.py is the thing that survives).
# ---------------------------------------------------------------------------

_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


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
    """Lists every job this dashboard process has run since it started --
    added after a real session where navigating away from a finished
    check-dead-links results page (an accidental click, nothing more)
    left no way back except digging through browser history or the Flask
    console log. _jobs is in-memory only, so this only shows jobs from
    the CURRENT process -- a restart clears it, same as every other job
    result in this file. Newest first."""
    with _jobs_lock:
        items = sorted(_jobs.items(), key=lambda kv: kv[0], reverse=True)

    def _job_link(job_id: str, job: dict) -> str:
        kind = job.get("kind", "unknown")
        status = job.get("status", "unknown")
        if kind == "dead_link_check" and status == "done":
            href = url_for("dead_links_results", job_id=job_id)
            detail = f"{len(job.get('dead', []))} dead, {len(job.get('uncertain', []))} inconclusive"
        else:
            href = url_for("job_status_page", job_id=job_id)
            detail = status
        return f"""<div class="card">
  <div class="card__company">{_esc(kind)}</div>
  <h3 class="card__title"><a href="{href}">{_esc(job_id)}</a></h3>
  <div class="card__meta">{_esc(detail)}</div>
</div>"""

    cards = "".join(_job_link(jid, j) for jid, j in items) or '<div class="empty-state">No jobs run yet this session.</div>'
    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Recent jobs</h1></div>
  <p class="sub">Jobs run since this dashboard process started -- lost when it restarts.</p>
  <div class="grid">{cards}</div>
  <p class="sub" style="margin-top:16px;"><a class="btn btn--secondary btn--small" href="{url_for('index')}">Back to postings</a></p>
</div>"""
    return _page("Recent jobs", body)


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

    def on_step(label: str) -> None:
        step_state["n"] += 1
        _set_job(job_id, step=step_state["n"], total_steps=total_steps, current=label)

    _set_job(
        job_id, status="running", posting_id=posting_id, kind="generate",
        company_name=company_name, job_title=job_title,
        step=0, total_steps=total_steps, current="starting…",
    )
    try:
        client = LLMClient()
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
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the polling page, don't just log it
        logger.exception("generation failed for posting %s", posting_id)
        _set_job(job_id, status="error", error=str(exc))


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
    _set_job(job_id, status="running", kind="score_batch", total=total, scored=0, skipped=0, current="")
    try:
        criteria = load_search_criteria()
        client = LLMClient()
        conn = get_connection()
        init_schema(conn)

        scored = 0
        skipped = 0
        for posting_id, company, title, location, status, description in posting_rows:
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

        _set_job(job_id, status="done", scored=scored, skipped=skipped, total=total)
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

    try:
        results = run_scout(on_company_done=_on_company_done)
        total_new = sum(r.new_postings for r in results)
        errors = [r for r in results if r.strategy == "error"]

        conn = get_connection()
        init_schema(conn)
        status = "ok" if not errors else "partial"
        detail = json.dumps({
            "companies_checked": len(results),
            "new_postings": total_new,
            "errors": [{"company": r.company_name, "error": r.error} for r in errors],
        })
        _log_run(conn, status, detail)

        _set_job(
            job_id, status="done",
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
            _set_job(job_id, current=f"{company} -- {title}")
            is_alive, detail = check_url_alive(url, limiter)
            entry = {"id": posting_id, "company": company, "title": title, "url": url, "detail": detail}
            if is_alive is False:
                dead.append(entry)
            elif is_alive is None:
                uncertain.append(entry)
            _set_job(job_id, checked=i, dead=dead, uncertain=uncertain)

        _set_job(job_id, status="done", checked=total, dead=dead, uncertain=uncertain)
    except Exception as exc:  # noqa: BLE001
        logger.exception("dead link check job %s failed", job_id)
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
        "page": max(1, int(args.get("page") or 1)) if str(args.get("page") or "1").isdigit() else 1,
    }


def _filters_query_string(filters: dict, **overrides) -> str:
    """Rebuilds the query string for pagination links, carrying every
    active filter forward except the ones being overridden (e.g. page)."""
    merged = {
        "keyword": filters["keyword"], "location": filters["location"],
        "bay_area": "1" if filters["bay_area"] else "", "company": filters["company"],
        "date_from": filters["date_from"], "date_to": filters["date_to"],
        "min_score": filters["min_score"], "page": filters["page"],
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
            ("min_score", filters["min_score"]),
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


def _filtered_postings(conn, filters: dict) -> tuple[list[tuple], list[tuple]]:
    """The SQL query + keyword/location filtering index() has always done,
    extracted so POST /postings/score-batch can run Scorer over EXACTLY
    the same filtered set the cards were rendered from -- one filtering
    implementation, two callers, not a second filter UI/logic path per
    the 2026-08-10 handoff's explicit instruction.

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
    return all_rows, filtered_rows


@app.route("/")
def index():
    conn = get_connection()
    init_schema(conn)

    filters = _parse_filters(request.args)
    all_rows, filtered_rows = _filtered_postings(conn, filters)

    drafts_by_posting = drafts_db.latest_draft_index(conn)
    companies = _distinct_companies(conn)
    filter_bar = _filter_bar_html(filters, companies)

    total = len(filtered_rows)
    per_page = POSTINGS_PER_PAGE
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(filters["page"], total_pages)
    page_rows = filtered_rows[(page - 1) * per_page : page * per_page]

    add_manual_link = f'<a class="btn btn--secondary btn--small" href="{url_for("posting_manual_form")}">+ Add posting manually</a>'
    run_scout_form = f"""<form method="post" action="{url_for('run_scout_route')}" class="inline-form">
      <button class="btn btn--small" type="submit">Run Scout</button></form>"""
    dead_link_form = f"""<form method="post" action="{url_for('check_dead_links_route')}" class="inline-form">
      <button class="btn btn--small btn--secondary" type="submit"
        title="Checks every non-stale posting's stored URL for a real HTTP 404/410 -- can take a while across hundreds of postings.">
        Check for dead links</button></form>"""
    recent_jobs_link = f'<a class="btn btn--small btn--secondary" href="{url_for("jobs_index")}">Recent jobs</a>'
    score_batch_form = _score_batch_form_html(filters, total)

    if not all_rows:
        body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Postings</h1>{run_scout_form}{dead_link_form}{recent_jobs_link}</div>
  {filter_bar}
  <div class="empty-state">No postings yet — click Run Scout above, or {add_manual_link}.</div>
</div>"""
        return _page("Postings", body)

    cards = []
    for posting_id, company, title, location, status, score, _first_seen_at, _description in page_rows:
        draft = drafts_by_posting.get(posting_id)
        quality_score = draft.final_score if draft else None
        link = (
            f'<a class="card__link" href="{url_for("posting_detail", posting_id=posting_id)}">View result</a>'
            if draft
            else f'<a class="card__link" href="{url_for("posting_detail", posting_id=posting_id)}">Generate</a>'
        )
        cards.append(
            f"""<div class="card">
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
  <div class="detail-header"><h1>Postings</h1>{run_scout_form}{dead_link_form}{recent_jobs_link}
    <p class="sub">{total} posting(s) match &middot; {len(all_rows)} total (excluding stale) &middot; {add_manual_link}</p></div>
  {filter_bar}
  {score_batch_form}
  <div class="grid">{''.join(cards)}</div>
  {pagination_html}
</div>"""
    return _page("Postings", body)


@app.route("/postings/<int:posting_id>")
def posting_detail(posting_id):
    conn = get_connection()
    init_schema(conn)
    posting = _get_posting(conn, posting_id)
    if posting is None:
        abort(404)
    draft = drafts_db.get_latest_draft(conn, posting_id)

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
  <a class="btn btn--secondary" href="{url_for('posting_resume_pdf', posting_id=posting_id)}">Download resume PDF</a>
  <a class="btn btn--secondary" href="{url_for('posting_cover_letter_pdf', posting_id=posting_id)}">Download cover letter PDF</a>
</div>
<p class="sub" style="margin-top:10px;">Generated {_esc(draft.generated_at)} &middot; {draft.revision_rounds + 1} round(s)</p>"""

    active_job = _active_generate_job_for_posting(posting_id)

    jd_full = _esc(posting["description"])
    regenerate_label = "Regenerate" if draft is not None else "Generate draft"

    if active_job is not None:
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

    body = f'<div class="dash-wrap">{header}{result_html}{gen_form}</div>'
    return _page(posting["title"], body)


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
    """
    job = _get_job(job_id)
    if job is None or job.get("kind") != "dead_link_check":
        abort(404)
    if job.get("status") != "done":
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


@app.route("/jobs/<job_id>")
def job_status_page(job_id):
    job = _get_job(job_id)
    if job is None:
        abort(404)
    body = f"""<div class="dash-wrap"><div class="spinner-wrap">
  <div class="spinner"></div>
  <p id="status">Starting…</p>
  <p id="detail" style="font-size:13px;color:var(--ink-faint);"></p>
  <p id="done-link"></p>
</div></div>
<script>
async function poll() {{
  const r = await fetch("{url_for('job_status_json', job_id=job_id)}");
  const j = await r.json();
  const el = document.getElementById("status");
  const detailEl = document.getElementById("detail");
  const linkEl = document.getElementById("done-link");

  if (j.status === "done") {{
    if (j.kind === "generate") {{
      window.location = "/postings/" + j.posting_id;
      return;
    }}
    if (j.kind === "dead_link_check") {{
      window.location = "{url_for('dead_links_results', job_id=job_id)}";
      return;
    }}
    if (j.kind === "score_batch") {{
      el.textContent = "Done.";
      detailEl.textContent = `Scored ${{j.scored}}, skipped ${{j.skipped}}, of ${{j.total}} filtered posting(s).`;
    }} else if (j.kind === "scout") {{
      el.textContent = "Done.";
      detailEl.textContent = `${{j.companies_checked}} companies checked, ${{j.new_postings}} new posting(s)` +
        (j.error_count ? `, ${{j.error_count}} error(s) -- see run_log for detail.` : ".");
    }} else {{
      el.textContent = "Done.";
    }}
    linkEl.innerHTML = '<a class="btn btn--small" href="{url_for("index")}">View postings</a>';
    return;
  }} else if (j.status === "error") {{
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
    return job


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


@app.route("/postings/<int:posting_id>/resume.pdf")
def posting_resume_pdf(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    settings = settings_db.get_candidate_settings(conn)
    html_out = render_resume_html(
        draft.result.final_draft,
        candidate_name=settings.candidate_name,
        contact_line=settings.contact_line,
    )
    pdf_bytes = html_to_pdf_bytes(html_out)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume_posting_{posting_id}.pdf"'},
    )


@app.route("/postings/<int:posting_id>/cover-letter.pdf")
def posting_cover_letter_pdf(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    settings = settings_db.get_candidate_settings(conn)
    html_out = render_cover_letter_html(
        draft.result.final_draft,
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="biohunter-dashboard")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    # threaded=True: required -- the index/detail pages must stay
    # responsive to GET/poll requests while a background generation
    # thread is running, not just while Flask itself avoids blocking.
    app.run(port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
