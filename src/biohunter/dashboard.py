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
"""
from __future__ import annotations

import argparse
import html
import logging
import threading
import uuid

from flask import Flask, Response, abort, redirect, request, url_for

from . import drafts_db
from .critic import ScoreResult, parse_score
from .db import get_connection, init_schema
from .diff import diff_revision_result
from .llm import LLMClient
from .report import _STYLE as _REPORT_STYLE
from .report import _score_bucket, render_posting_report
from .resume_pdf import html_to_pdf_bytes, render_cover_letter_html, render_resume_html
from .revision import run_revision_loop

logger = logging.getLogger(__name__)

app = Flask(__name__)

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
    _set_job(job_id, status="running", posting_id=posting_id)
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

.detail-header { margin-bottom: 20px; }
.detail-header h1 { margin: 0 0 4px; font-size: 24px; }
.detail-header .sub { color: var(--ink-soft); font-size: 14.5px; }

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
    bucket = _score_bucket(score)
    label = f"{score}/10" if score is not None else "not generated"
    return f'<span class="badge badge--{bucket}">{_esc(label)}</span>'


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    conn = get_connection()
    init_schema(conn)
    rows = conn.execute(
        """SELECT postings.id, companies.name, postings.title, postings.location, postings.status
           FROM postings JOIN companies ON postings.company_id = companies.id
           WHERE postings.status != 'stale'
           ORDER BY companies.name, postings.title"""
    ).fetchall()
    drafts_by_posting = drafts_db.latest_draft_index(conn)

    if not rows:
        body = f'<div class="dash-wrap"><div class="empty-state">No postings yet — run <code>biohunter run-scout</code> first.</div></div>'
        return _page("Postings", body)

    cards = []
    for posting_id, company, title, location, status in rows:
        draft = drafts_by_posting.get(posting_id)
        score = draft.final_score if draft else None
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
  <div class="card__footer">{_score_badge(score)}{link}</div>
</div>"""
        )

    body = f"""<div class="dash-wrap">
  <div class="detail-header"><h1>Postings</h1><p class="sub">{len(rows)} posting(s)</p></div>
  <div class="grid">{''.join(cards)}</div>
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
    _set_job(job_id, status="queued", posting_id=posting_id)
    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, posting_id, posting["company"], posting["title"], description, revision_rounds, think),
        daemon=True,
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
</div></div>
<script>
async function poll() {{
  const r = await fetch("{url_for('job_status_json', job_id=job_id)}");
  const j = await r.json();
  const el = document.getElementById("status");
  if (j.status === "done") {{
    window.location = "/postings/" + j.posting_id;
  }} else if (j.status === "error") {{
    el.textContent = "Generation failed: " + j.error;
  }} else {{
    el.textContent = j.status === "running" ? "Running Writer \\u2192 Critic \\u2192 Revision\\u2026 (a few minutes on local models)" : "Queued\\u2026";
    setTimeout(poll, 2500);
  }}
}}
poll();
</script>"""
    return _page("Generating", body)


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
