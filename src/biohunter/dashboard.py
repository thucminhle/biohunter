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
("generate" | "score_batch" | "scout") so job_status_page's polling JS
can show the right progress shape for each, since only score_batch's
total is known upfront (an exact filtered-posting count) and can show
real "N of M" progress; scout's isn't -- run_scout()'s own module isn't
in this codebase's dashboard.py dependency chain and wasn't re-verified
before this was written, so its button intentionally shows an honest
"running, can't report fine-grained progress" status rather than a
fabricated progress bar. "Score these N filtered postings" runs Scorer
over EXACTLY the postings-index's current filter set (same
keyword_filter_match() call the cards already render from, via a shared
_filtered_postings() helper extracted from index() for this) -- not a
second, separate filter UI, per the 2026-08-10 handoff's explicit
instruction.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import threading
import uuid

from flask import Flask, Response, abort, redirect, request, url_for

from . import drafts_db
from .cli import DEFAULT_BAY_AREA_LOCATIONS, _log_run, keyword_filter_match
from .config import load_search_criteria
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


def _run_generation(
    job_id: str,
    posting_id: int,
    company_name: str,
    job_title: str,
    job_description: str,
    revision_rounds: int,
    think: bool,
) -> None:
    """Runs in a background thread, started by POST /postings/<id>/generate.
    Opens its own DB connection rather than sharing the request's --
    libsql connections aren't guaranteed thread-safe to share across
    threads, and this thread outlives the request that started it."""
    _set_job(job_id, status="running", posting_id=posting_id, kind="generate")
    try:
        client = LLMClient()
        result = run_revision_loop(
            client,
            company_name=company_name,
            job_title=job_title,
            job_description=job_description,
            revision_rounds=revision_rounds,
            think=think,
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

    KNOWN GAP, stated rather than papered over: run_scout()'s own module
    (src/biohunter/scout/) was not part of this session's uploads, so
    whether it reports progress incrementally as it checks each company
    is unverified. This function does NOT fabricate a per-company
    progress count -- job_status_page shows an honest "running, can't
    report fine-grained progress" message for kind='scout' rather than a
    bar that might be lying. If run_scout() turns out to support a
    progress callback, wiring real progress through here is a small
    follow-up, not a rewrite.
    """
    _set_job(job_id, status="running", kind="scout")
    try:
        results = run_scout()
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


# ---------------------------------------------------------------------------
# Small DB helpers local to the dashboard -- one posting lookup shape
# every route below needs, kept here rather than in db.py since it's a
# dashboard-specific join (postings + companies), not a schema concern.
# ---------------------------------------------------------------------------


def _get_posting(conn, posting_id: int) -> dict | None:
    row = conn.execute(
        """SELECT postings.id, companies.name, postings.title, postings.location,
                  postings.url, postings.description, postings.status
           FROM postings JOIN companies ON postings.company_id = companies.id
           WHERE postings.id = ?""",
        (posting_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("id", "company", "title", "location", "url", "description", "status")
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
<div class="topbar"><div class="topbar__wrap"><a href="{url_for('index')}">BioHunter</a></div></div>
{body}
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
    rows = conn.execute("SELECT DISTINCT name FROM companies ORDER BY name").fetchall()
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
    score_batch_form = _score_batch_form_html(filters, total)

    if not all_rows:
        body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Postings</h1>{run_scout_form}</div>
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
  <div class="detail-header"><h1>Postings</h1>{run_scout_form}
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

    header = f"""<div class="detail-header">
  <h1>{_esc(posting['title'])}</h1>
  <p class="sub">{_esc(posting['company'])} &middot; {_esc(posting['location'] or 'Location n/a')}
  &middot; <a href="{_esc(posting['url'])}" target="_blank">original posting</a></p>
</div>"""

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

    jd_preview = _esc(posting["description"][:400]) + ("…" if len(posting["description"]) > 400 else "")
    regenerate_label = "Regenerate" if draft is not None else "Generate draft"
    gen_form = f"""<details style="margin-top:24px;"><summary style="cursor:pointer;font-weight:600;">Job description (stored)</summary>
  <p class="sub" style="white-space:pre-wrap;">{jd_preview}</p></details>
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

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", posting_id=posting_id, kind="generate")
    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, posting_id, posting["company"], posting["title"], description, revision_rounds, think),
        daemon=True,
    )
    thread.start()
    return redirect(url_for("job_status_page", job_id=job_id))


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
    detailEl.textContent = "Checking company career pages -- can take several minutes; fine-grained progress isn't available for this job.";
    setTimeout(poll, 2500);
  }} else {{
    el.textContent = j.status === "running" ? "Running Writer \\u2192 Critic \\u2192 Revision\\u2026 (a few minutes on local models)" : "Queued\\u2026";
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
    )
    return Response(html_out, mimetype="text/html")


@app.route("/postings/<int:posting_id>/resume.pdf")
def posting_resume_pdf(posting_id):
    conn = get_connection()
    init_schema(conn)
    draft = drafts_db.get_latest_draft(conn, posting_id)
    if draft is None:
        abort(404)
    html_out = render_resume_html(draft.result.final_draft)
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
    html_out = render_cover_letter_html(draft.result.final_draft)
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

    company_id = _find_or_create_company_light(conn, company_name, fallback_url=url)

    existing = conn.execute(
        "SELECT id FROM postings WHERE company_id = ? AND url = ?", (company_id, url)
    ).fetchone()
    if existing:
        # Same URL already stored for this company -- treat resubmission as
        # "take me to the one I already have" rather than erroring on the
        # UNIQUE(company_id, url) constraint, matching _upsert_postings()'s
        # own re-sighting semantics in scout/detector.py.
        return redirect(url_for("posting_detail", posting_id=existing[0]))

    cur = conn.execute(
        """INSERT INTO postings (company_id, title, url, location, description, status)
           VALUES (?, ?, ?, ?, ?, 'new')""",
        (company_id, title, url, location, description),
    )
    conn.commit()
    posting_id = cur.lastrowid
    return redirect(url_for("posting_detail", posting_id=posting_id))


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
