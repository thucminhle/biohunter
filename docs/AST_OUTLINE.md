# Project AST Outline
> Auto-generated high-detail code skeleton for AI context.

## `src/biohunter/__init__.py`
```python
```

## `src/biohunter/ats/__init__.py`
```python
REGISTRY: dict[str, ATSAdapter] = {'greenhouse': GreenhouseAdapter(), 'lever': LeverAdapter(), 'ashby': AshbyAdapter(), 'workday': WorkdayAdapter(), 'jobvite': JobviteAdapter(), 'jobsyn': JobsynAdapter()}
```

## `src/biohunter/ats/ashby.py`
```python
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
class AshbyAdapter(ATSAdapter):
    name = 'ashby'
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        ...


```

## `src/biohunter/ats/base.py`
```python
class RawPosting:
    """Normalized posting shape every ATS adapter (and the fallback scraper) returns."""
    title: str
    url: str
    location: str | None = None
    description: str | None = None

class ATSAdapter(abc.ABC):
    """One adapter per ATS platform. Each wraps that platform's public JSON API."""
    name: str
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        """Return all currently-listed postings for the given company slug."""
        ...


```

## `src/biohunter/ats/greenhouse.py`
```python
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
class GreenhouseAdapter(ATSAdapter):
    name = 'greenhouse'
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        ...


```

## `src/biohunter/ats/jobsyn.py`
```python
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
_SEARCH_URL = 'https://prod-search-api.jobsyn.org/api/v1/solr/search'
_PAGE_SIZE = 50
class JobsynAdapter(ATSAdapter):
    """DirectEmployers' National Labor Exchange (jobsyn.org) backend --"""
    name = 'jobsyn'
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        ...

    def _to_raw_posting(job: dict, origin: str) -> RawPosting:
        ...


```

## `src/biohunter/ats/jobvite.py`
```python
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
class JobviteAdapter(ATSAdapter):
    """Unlike Greenhouse/Lever/Ashby, Jobvite doesn't expose a public,"""
    name = 'jobvite'
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        ...


```

## `src/biohunter/ats/lever.py`
```python
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
class LeverAdapter(ATSAdapter):
    name = 'lever'
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        ...


```

## `src/biohunter/ats/workday.py`
```python
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
_PAGE_SIZE = 20
class WorkdayAdapter(ATSAdapter):
    """Workday doesn't publish a documented public API the way Greenhouse/"""
    name = 'workday'
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        ...

    def _fetch_one_site(self, host: str, tenant: str, site: str) -> list[RawPosting]:
        ...


```

## `src/biohunter/cli.py`
```python
# Usage:
#     python -m biohunter.cli run-scout
#     python -m biohunter.cli list-postings [--exclude KEYWORD,...] [--include KEYWORD,...] [--company NAME]
#     python -m biohunter.cli score-postings [--rescore] [--limit N] [--model ROLE=VALUE ...] [--think]
#     python -m biohunter.cli verify-llm [--role ROLE ...] [--model ROLE=VALUE ...] [--include-anthropic]
#     python -m biohunter.cli verify-writer --company NAME [--title TITLE]
#         (--job-description TEXT | --job-description-file PATH) [--model ROLE=VALUE ...]
#     python -m biohunter.cli verify-critic --company NAME [--title TITLE]
#         (--job-description TEXT | --job-description-file PATH) [--model ROLE=VALUE ...] [--think]
#     python -m biohunter.cli verify-revision --company NAME [--title TITLE]
#         (--job-description TEXT | --job-description-file PATH) [--model ROLE=VALUE ...]
#         [--revision-rounds N] [--think] [--show-diff]

DEFAULT_REPORT_DIR = 'reports'
DEFAULT_EXCLUDE_KEYWORDS = ['postdoc', 'post-doctoral', 'post doctoral', 'intern', 'internship', 'co-op']
DEFAULT_BAY_AREA_LOCATIONS = ['bay area', 'san francisco', 'south san francisco', 'oakland', 'berkeley', 'san jose', 'redwood city', 'foster city', 'fremont', 'palo alto', 'menlo park', 'emeryville', 'mountain view', 'santa clara', 'hayward', 'san mateo', 'sunnyvale', 'vacaville', 'richmond, ca', 'alameda']
def keyword_filter_match(text: str, include: list[str], exclude: list[str]) -> bool:
    """The exact substring-matching predicate cmd_list_postings has always"""
    ...

def _log_run(conn, status: str, detail: str) -> None:
    ...

def _parse_model_overrides(values: list[str]) -> dict[str, str]:
    """Turns repeated --model role=value flags into the overrides dict"""
    ...

def cmd_run_scout(_args: argparse.Namespace) -> None:
    ...

def cmd_list_postings(args: argparse.Namespace) -> None:
    ...

def cmd_score_postings(args: argparse.Namespace) -> None:
    """Runs Scorer (scorer.score_posting) over stored postings and writes"""
    ...

def cmd_verify_llm(args: argparse.Namespace) -> None:
    """Step 0 smoke test: send one trivial message through every role"""
    ...

def cmd_verify_writer(args: argparse.Namespace) -> None:
    """Runs the full native Writer pipeline (writer.generate_draft) end"""
    ...

def cmd_verify_critic(args: argparse.Namespace) -> None:
    """Runs the full native Writer pipeline against one real posting"""
    ...

def cmd_verify_revision(args: argparse.Namespace) -> None:
    """Runs the full revision loop (revision.run_revision_loop) against"""
    ...

def cmd_report(args: argparse.Namespace) -> None:
    """Runs the full Writer<->Critic revision loop against one real"""
    ...

def main() -> None:
    ...

```

## `src/biohunter/config.py`
```python
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPANIES_YAML = _REPO_ROOT / 'config' / 'companies.yaml'
_COMPANIES_YAML_EXAMPLE = _REPO_ROOT / 'config' / 'companies.example.yaml'
_CRITERIA_YAML = _REPO_ROOT / 'config' / 'search_criteria.yaml'
_CRITERIA_YAML_EXAMPLE = _REPO_ROOT / 'config' / 'search_criteria.example.yaml'
class SearchCriteria:
    location_include: list[str] = dataclasses.field(default_factory=list)
    location_exclude: list[str] = dataclasses.field(default_factory=list)
    title_include: list[str] = dataclasses.field(default_factory=list)
    title_exclude: list[str] = dataclasses.field(default_factory=list)

def load_search_criteria() -> SearchCriteria:
    """The swappable piece: this file (not any code) is what defines what"""
    ...

class CompanyConfig:
    name: str
    careers_url: str
    ats_type: str | None = None
    ats_slug: str | None = None
    css_selector: str | None = None
    renderer: str | None = None

def load_companies() -> list[CompanyConfig]:
    ...

```

## `src/biohunter/critic.py`
```python
# Critic agent: one blind-review LLM call over a completed WriterDraft,
# producing freeform critique text a human (and eventually a revision
# loop) can act on.
#
# Deliberately NOT built on selection.py's machinery (parse_json_response,
# exact-match validation, catalog fallback) -- there's no catalog to
# select from here, just a draft to review, so that machinery would be
# unused abstraction. This mirrors stitch_cover_letter()'s shape instead:
# one prompt, one LLM call, return the text.
#
# Per ADR-0006 / the 2026-08-06 handoff, this is Phase 2 item #1. It is
# intentionally DB-agnostic and persistence-agnostic -- critique_draft()
# takes a draft's pieces and returns text, nothing more. Wiring this to
# `awaiting_review` status, storage, or a revision loop is item #2's
# concern, not this module's.

logger = logging.getLogger(__name__)
CRITIC_INSTRUCTION = "You are a skeptical, detail-oriented hiring manager and ATS specialist reviewing a tailored resume and cover letter against a specific job description, before the candidate submits it. Be direct and specific -- vague praise is not useful here. Quote the exact bullet, phrase, or sentence you are critiquing wherever possible, don't paraphrase it.\n\nOrganize your response under exactly these six headers, in this order, each as a markdown '## ' heading:\n\n## ATS & Keyword Coverage\nIdentify important keywords/skills from the job description that are MISSING from the resume, and note any that are present but buried or phrased differently than the job posting uses them.\n\n## Unsupported Claims\nFlag any bullet, summary line, or cover letter sentence that asserts something the rest of the resume doesn't substantiate (an unearned superlative, a skill claimed nowhere else, a metric that seems invented).\n\n## Weak Bullets\nCall out specific Professional Experience bullets that are vague, generic, lack a concrete result, or don't clearly connect to this job description. Quote them.\n\n## Weak Summary\nAssess whether the tailored summary paragraph actually pulls its weight for THIS posting, or reads generic enough to have been sent anywhere.\n\n## Cover Letter Critique\nAssess tone, specificity, and whether the letter reads as genuinely tailored to this company/role or as a template with placeholders swapped.\n\n## Overall Recommendation\nOne short paragraph: submit as-is, submit with minor edits, or needs real revision -- and the single highest-leverage change to make if not submitting as-is.\n\n## Score\nYour honest assessment of how ready this draft is to submit for THIS posting, as a single integer from 1 (not ready, needs a full rewrite) to 10 (submit as-is, no changes needed). This must be the ONLY line in this section -- no preamble, no extra commentary, exactly this format and nothing else:\nSCORE: <integer 1-10> -- <one-sentence rationale>"
_SCORE_LINE_RE = re.compile('SCORE:\\s*(\\d{1,2})\\s*[-\\u2013\\u2014:]+\\s*(.+)', re.IGNORECASE)
def critique_draft(llm: LLMClient, role: str, company_name: str, job_title: str, job_description: str, tailored_summary: str, tailored_bullets: str, cover_letter: str, think: bool=False) -> str:
    """Runs one blind-review pass over an already-assembled draft."""
    ...

class ScoreResult:
    score: int | None
    rationale: str | None

def parse_score(critique_text: str) -> ScoreResult:
    """Extracts the '## Score' section's SCORE: line from critique_draft()'s"""
    ...

```

## `src/biohunter/dashboard.py`
```python
# Local dashboard: browse Scout's postings, trigger Writer -> Critic ->
# Revision generation for one posting at a time from the browser, review
# the result, and export a plain resume/cover-letter PDF to actually
# submit -- the "dynamic dashboard" ADR-0006 explicitly deferred
# ("revisit only once there's a concrete need"), built now on direct
# request rather than by default.
#
# Architecture, stated explicitly per this project's own working style
# (name a real behavior/scope change, don't let it look like a small
# addition): this module calls run_revision_loop()/diff_revision_result()
# DIRECTLY -- the same functions cli.py's `report` command already
# calls -- rather than shelling out to the CLI as a subprocess. One
# pipeline implementation either way (writer.py/critic.py/revision.py
# are unchanged and untouched by this file); this just skips the extra
# process boundary a subprocess approach would have added.
#
# Single local Flask process, single user, no auth -- this runs on your
# own machine, it is not a deployed service, and nothing here should be
# exposed past localhost. Generation takes real minutes against local
# Ollama models, so it NEVER runs on the request thread: POST
# /postings/<id>/generate starts a background thread and returns
# immediately with a job id; the browser polls /jobs/<job_id>.json until
# it's done, matching the "don't hang the tab for a multi-minute LLM
# run" reasoning from the design discussion that led to this file.
#
# A crashed/restarted dashboard process loses any IN-FLIGHT (not yet
# completed) generation -- completed ones are already durably persisted
# via drafts_db.py by the time a background thread finishes, so nothing
# that finished is ever lost, only a run that was still running.
#
# Run with: python -m biohunter.dashboard [--port 5050] [--debug]
#
# New dependency: `pip install flask`. PDF export (resume_pdf.py) needs
# Playwright separately -- see that module's docstring.
#
# 2026-08-09 additions (postings-index filtering + manual entry): the index
# route now supports keyword/location/company/date/score filtering and
# pagination, and there's a manual-add flow (GET/POST /postings/manual) for
# postings Scout didn't find on its own. Filtering reuses cli.py's
# keyword_filter_match() and DEFAULT_BAY_AREA_LOCATIONS -- the exact
# substring-matching logic list-postings already used -- rather than a
# second, dashboard-only reimplementation of the same heuristic. Score
# filtering is against postings.score (scorer.py's job-FIT score, run via
# `biohunter score-postings`), NOT drafts.final_score (Critic's resume-
# quality score, which only exists after a draft has been generated) --
# see the 2026-08-09 handoff for why those are two different things.

logger = logging.getLogger(__name__)
app = Flask(__name__)
POSTINGS_PER_PAGE = 60
_jobs: dict[str, dict] = {}
def _set_job(job_id: str) -> None:
    ...

def _get_job(job_id: str) -> dict | None:
    ...

def _run_generation(job_id: str, posting_id: int, company_name: str, job_title: str, job_description: str, revision_rounds: int, think: bool) -> None:
    """Runs in a background thread, started by POST /postings/<id>/generate."""
    ...

def _get_posting(conn, posting_id: int) -> dict | None:
    ...

_DASHBOARD_STYLE = '\n.topbar {\n  background: var(--ink); color: #F6F7F5; padding: 18px 24px;\n}\n.topbar a { color: #F6F7F5; text-decoration: none; font-weight: 650; font-size: 15px; }\n.topbar__wrap { max-width: 1040px; margin: 0 auto; }\n.dash-wrap { max-width: 1040px; margin: 0 auto; padding: 28px 24px 96px; }\n\n.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }\n.card {\n  background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px;\n  padding: 18px 20px; display: flex; flex-direction: column; gap: 6px;\n}\n.card__company { font-size: 12px; font-family: var(--mono); color: var(--accent); text-transform: uppercase; letter-spacing: 0.05em; }\n.card__title { font-size: 16px; font-weight: 650; margin: 0; }\n.card__meta { font-size: 12.5px; color: var(--ink-faint); }\n.card__footer { margin-top: 10px; display: flex; align-items: center; justify-content: space-between; }\n.badge {\n  font-family: var(--mono); font-size: 12px; padding: 3px 9px; border-radius: 3px; font-weight: 600;\n}\n.badge--good { color: var(--good); background: var(--good-bg); }\n.badge--mid { color: var(--mid); background: var(--mid-bg); }\n.badge--low { color: var(--low); background: var(--low-bg); }\n.badge--unknown, .badge--none { color: var(--unknown); background: var(--unknown-bg); }\n.card__link { font-size: 13px; font-weight: 600; color: var(--accent); text-decoration: none; }\n.card__link:hover { text-decoration: underline; }\n\n.detail-header { margin-bottom: 20px; }\n.detail-header h1 { margin: 0 0 4px; font-size: 24px; }\n.detail-header .sub { color: var(--ink-soft); font-size: 14.5px; }\n\n.jd-box { width: 100%; min-height: 240px; font-family: var(--mono); font-size: 13px;\n  border: 1px solid var(--hairline); border-radius: 4px; padding: 12px; resize: vertical; }\n.form-row { margin: 14px 0; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }\nlabel { font-size: 13.5px; color: var(--ink-soft); }\ninput[type=number] { width: 64px; font-family: var(--mono); padding: 4px 6px; border: 1px solid var(--hairline); border-radius: 3px; }\n\n.btn, .btn:link, .btn:visited {\n  font-family: var(--sans); font-size: 14px; font-weight: 650; padding: 10px 18px;\n  border-radius: 4px; border: none; cursor: pointer; background: var(--accent); color: #fff;\n  text-decoration: none; display: inline-block;\n}\n.btn:hover { opacity: 0.92; }\n.btn--secondary, .btn--secondary:link, .btn--secondary:visited {\n  background: var(--panel); color: var(--ink); border: 1px solid var(--hairline);\n}\n.card__link, .card__link:link, .card__link:visited { text-decoration: none; }\n.btn-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }\n\n.result-summary { display: flex; align-items: center; gap: 20px; background: var(--panel);\n  border: 1px solid var(--hairline); border-radius: 4px; padding: 20px; margin: 20px 0; }\n.result-summary .dial { min-width: 90px; }\n\n.spinner-wrap { text-align: center; padding: 80px 20px; }\n.spinner {\n  width: 36px; height: 36px; margin: 0 auto 20px; border-radius: 50%;\n  border: 3px solid var(--hairline); border-top-color: var(--accent);\n  animation: spin 0.8s linear infinite;\n}\n@keyframes spin { to { transform: rotate(360deg); } }\n\n.empty-state { color: var(--ink-faint); text-align: center; padding: 60px 20px; }\n\n.filter-bar { background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px;\n  padding: 16px 18px; margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 14px 20px; align-items: flex-end; }\n.filter-bar .field { display: flex; flex-direction: column; gap: 4px; }\n.filter-bar input[type=text], .filter-bar input[type=date], .filter-bar select, .filter-bar input[type=number] {\n  font-family: var(--sans); font-size: 13.5px; padding: 6px 8px; border: 1px solid var(--hairline);\n  border-radius: 3px; width: auto; }\n.filter-bar .checkbox-field { display: flex; align-items: center; gap: 6px; }\n.filter-bar .checkbox-field label { margin: 0; }\n.filter-bar .actions { display: flex; gap: 8px; margin-left: auto; }\n.btn--small, .btn--small:link, .btn--small:visited { padding: 6px 14px; font-size: 13px; }\n\n.pagination { display: flex; justify-content: center; gap: 6px; margin-top: 28px; }\n.pagination a, .pagination span { font-family: var(--mono); font-size: 13px; padding: 6px 12px;\n  border: 1px solid var(--hairline); border-radius: 3px; text-decoration: none; color: var(--ink); }\n.pagination .current { background: var(--accent); color: #fff; border-color: var(--accent); }\n\ntextarea.manual-jd { width: 100%; min-height: 180px; font-family: var(--mono); font-size: 13px;\n  border: 1px solid var(--hairline); border-radius: 4px; padding: 12px; resize: vertical; }\ninput[type=text].wide { width: 100%; font-family: var(--sans); font-size: 14px; padding: 8px 10px;\n  border: 1px solid var(--hairline); border-radius: 4px; }\n'
def _page(title: str, body: str) -> str:
    ...

def _score_badge(score: int | None) -> str:
    """Critic's resume-QUALITY score (drafts.final_score) -- only exists"""
    ...

def _fit_score_badge(score: float | None) -> str:
    """Scorer's job-FIT score (postings.score) -- exists once"""
    ...

def _parse_filters(args) -> dict:
    ...

def _filters_query_string(filters: dict) -> str:
    """Rebuilds the query string for pagination links, carrying every"""
    ...

def _distinct_companies(conn) -> list[str]:
    ...

def _filter_bar_html(filters: dict, companies: list[str]) -> str:
    ...

def index():
    ...

def posting_detail(posting_id):
    ...

def _generate_options_html() -> str:
    ...

def generate(posting_id):
    ...

def job_status_page(job_id):
    ...

def job_status_json(job_id):
    ...

def posting_report(posting_id):
    ...

def posting_resume_pdf(posting_id):
    ...

def posting_cover_letter_pdf(posting_id):
    ...

def _find_or_create_company_light(conn, name: str, fallback_url: str) -> int:
    ...

def posting_manual_form():
    ...

def posting_manual_create():
    ...

def main() -> None:
    ...

```

## `src/biohunter/db.py`
```python
# DB connection + schema init.
#
# Dev mode (default): plain local SQLite file at data/biohunter.db.
# Turso mode: set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars and the
# same code becomes an embedded-replica sync'd against your Turso db --
# no code changes needed, per libsql-experimental's design.

_SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / 'schema.sql'
_DEFAULT_LOCAL_DB = pathlib.Path(__file__).resolve().parents[2] / 'data' / 'biohunter.db'
def get_connection(local_path: str | None=None):
    """Return a libsql connection, local-only or Turso-synced depending on env."""
    ...

def init_schema(conn) -> None:
    """Apply schema.sql. Safe to call repeatedly (uses CREATE TABLE IF NOT EXISTS)."""
    ...

def _split_statements(sql: str) -> list[str]:
    ...

```

## `src/biohunter/detect_ats.py`
```python
# Auto-detect ATS type + slug for a list of companies, and write/merge the
# result into config/companies.yaml.
#
# Usage:
#     python -m biohunter.detect_ats --input config/companies_input.yaml
#
# Input file format (config/companies_input.yaml):
#     companies:
#       - name: Genentech
#         careers_url: "https://careers.gene.com/us/en"
#       - name: Some Biotech
#         careers_url: "https://somebiotech.com/careers"
#
# For each company:
#   1. Fetches careers_url (following redirects).
#   2. Scans the *final* URL and the page HTML for Greenhouse/Lever/Ashby/
#      Workday fingerprints (many companies embed an ATS board via iframe,
#      so the fingerprint often lives in the HTML, not the URL you started
#      with -- this is why we search page content, not just the final URL).
#   3. Fills in ats_type/ats_slug automatically on a match.
#   4. Leaves ats_type blank + adds a TODO comment for manual css_selector
#      setup on no match.
#
# Existing entries in companies.yaml that already have an ats_type set are
# left untouched, unless --force is passed.

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPANIES_YAML = _REPO_ROOT / 'config' / 'companies.yaml'
_PATTERNS: list[tuple[str, re.Pattern]] = [('greenhouse', re.compile('(?:job-)?boards(?:-api)?\\.greenhouse\\.io/(?:v1/boards/)?([a-zA-Z0-9_-]+)')), ('lever', re.compile('jobs\\.lever\\.co/([a-zA-Z0-9_-]+)')), ('ashby', re.compile('jobs\\.ashbyhq\\.com/([a-zA-Z0-9_-]+)')), ('workday', re.compile('([a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+)\\.myworkdayjobs\\.com/([a-zA-Z0-9_-]+)')), ('jobvite', re.compile('jobs\\.jobvite\\.com/([a-zA-Z0-9_-]+)'))]
def detect_one(name: str, careers_url: str, limiter: RateLimiter) -> dict:
    """Returns a dict shaped like a companies.yaml entry."""
    ...

def load_input(path: pathlib.Path) -> list[dict]:
    ...

def load_existing() -> dict[str, dict]:
    ...

def main() -> None:
    ...

```

## `src/biohunter/diff.py`
```python
# Resume Diff: renders what changed (or didn't) between consecutive rounds
# of a revision loop (ADR-0006 Phase 2 item #1, per the 2026-08-07 handoff).
#
# RevisionResult.rounds already carries every round's full WriterDraft --
# this module adds no new data, it's a rendering pass over what
# revision.py already produces. Like critic.py/revision.py, it stays
# persistence-agnostic: pure functions in, dataclasses out, no printing,
# no storage. cli.py decides how to display the result.
#
# Diffs are computed per-section (summary / bullets / cover letter)
# rather than as one blob over the whole draft, matching how every other
# part of this project (writer.py's branches, verify-revision's printout)
# already treats these three pieces as independent.
#
# Unchanged sections are reported explicitly (changed=False, empty diff
# text) rather than omitted. This project already got burned once this
# session by a branch silently no-op'ing and looking indistinguishable
# from "revision happened" -- a diff step that quietly skips unchanged
# sections would hide exactly that failure mode instead of surfacing it.

_DIFF_SECTIONS: tuple[tuple[str, str], ...] = (('tailored_summary', 'Tailored Summary'), ('tailored_bullets', 'Tailored Bullets'), ('cover_letter', 'Cover Letter'))
class SectionDiff:
    section: str
    changed: bool
    diff_text: str

class RoundDiff:
    round_from: int
    round_to: int
    sections: list[SectionDiff]

def diff_drafts(prev: WriterDraft, curr: WriterDraft, from_label: str='before', to_label: str='after') -> list[SectionDiff]:
    """Diffs two drafts section-by-section (order: summary, bullets,"""
    ...

def diff_revision_result(result: RevisionResult) -> list[RoundDiff]:
    """Diffs every consecutive pair of rounds in a RevisionResult."""
    ...

```

## `src/biohunter/drafts_db.py`
```python
# Persistence for generated drafts (Writer -> Critic -> Revision output),
# keyed to a posting. Added alongside the dashboard -- see schema.sql's
# `drafts` table comment for why this is a new table rather than columns
# bolted onto `postings`.
#
# Nothing in writer.py/critic.py/revision.py/diff.py changes because of
# this module. Those stay exactly what they were: pure functions that
# take data and return dataclasses, with zero knowledge that a database
# exists. This module is the only place that knows how a RevisionResult
# gets serialized to/from a DB row -- same "one module owns one concern"
# split as the rest of this project.
#
# conn is whatever db.get_connection() returns (libsql_experimental,
# SQLite-compatible per schema.sql's own comment) -- every function here
# takes it as a parameter rather than opening its own connection, same
# convention cli.py's commands already use.

def _draft_to_dict(d: WriterDraft) -> dict:
    ...

def _draft_from_dict(d: dict) -> WriterDraft:
    ...

def _result_to_dict(result: RevisionResult) -> dict:
    ...

def _result_from_dict(d: dict) -> RevisionResult:
    ...

class DraftRecord:
    id: int
    posting_id: int
    generated_at: str
    revision_rounds: int
    final_score: int | None
    result: RevisionResult

def save_draft(conn, posting_id: int, result: RevisionResult) -> int:
    """Persists one generation run and returns its new drafts.id."""
    ...

def _row_to_record(row) -> DraftRecord:
    ...

def get_latest_draft(conn, posting_id: int) -> DraftRecord | None:
    ...

def get_draft_by_id(conn, draft_id: int) -> DraftRecord | None:
    ...

def latest_draft_index(conn) -> dict[int, DraftRecord]:
    """One query for the dashboard's posting list: the latest draft per"""
    ...

```

## `src/biohunter/llm.py`
```python
class LLMResponse:
    text: str
    model: str
    provider: str

class LLMBackend(Protocol):
    """Anything that can turn a list of chat messages into a response."""
    def chat(self, messages: list[dict], model: str) -> LLMResponse:
        ...


class AnthropicClient:
    """Wraps Anthropic's SDK behind the LLMBackend protocol."""
    def __init__(self) -> None:
        ...

    def chat(self, messages: list[dict], model: str) -> LLMResponse:
        ...


class OllamaNativeClient:
    """Hits Ollama's NATIVE /api/chat endpoint -- not the OpenAI-compatible"""
    def __init__(self, base_url: str, api_key: str | None=None) -> None:
        ...

    def chat(self, messages: list[dict], model: str) -> LLMResponse:
        ...


class OpenAICompatibleClient:
    """One backend for both Ollama and MLX — they expose the same"""
    def __init__(self, base_url: str, api_key: str | None=None) -> None:
        ...

    def chat(self, messages: list[dict], model: str) -> LLMResponse:
        ...


_ENV_VAR_PATTERN = re.compile('\\$\\{(\\w+)\\}')
def _resolve_env(value: Any) -> Any:
    """roles.yaml uses ${VAR} for things like webhook URLs pulled from"""
    ...

class LLMClient:
    """Resolves a role name (e.g. "writer_selection") to the right"""
    def __init__(self, roles_path: str | Path='config/roles.yaml', overrides: dict[str, str] | None=None) -> None:
        ...

    def roles(self) -> dict[str, dict]:
        """Read-only view of the loaded roles.yaml, for callers (like the"""
        ...

    def _get_backend(self, provider: str, base_url: str | None, api_key: str | None) -> LLMBackend:
        ...

    def complete(self, role: str, messages: list[dict]) -> LLMResponse:
        ...


```

## `src/biohunter/qdrant.py`
```python
QDRANT_URL = os.environ.get('QDRANT_URL', 'http://localhost:6333')
COLLECTION = 'resume_content'
def scroll(filter_: dict, limit: int=20) -> list[dict]:
    """POST .../points/scroll — same call every "fetch X catalog" node in"""
    ...

def fetch_by_section_type(section_type: str | list[str], limit: int=20, extra_filter: dict | None=None) -> list[dict]:
    """Fetch every point whose payload.section_type matches, returning"""
    ...

```

## `src/biohunter/report.py`
```python
# Static HTML activity report for a single posting (ADR-0006 decision #3 /
# ROADMAP Phase 2's `biohunter report` item), per the 2026-08-07 Diff-Score-
# BulletFix handoff's "FIRST THING TO DO NEXT SESSION" list, item 3.
#
# Scope of this pass, per explicit direction: single-posting report now,
# a multi-posting index later. This module renders ONE posting's full
# pipeline output -- Writer's draft, Critic's critique, the ATS score,
# and the round-by-round revision history/diffs -- as one self-contained
# HTML file. No server, no JS framework, no network fetch (fonts are the
# system stack only -- see the `morning` skill's font gotcha for why that
# matters in this sandbox; nothing here needs it anyway).
#
# Like critic.py/revision.py/diff.py, this module is persistence-agnostic
# and pure: render_posting_report() takes a RevisionResult (plus the
# posting's own company/title/job description and optional round diffs)
# and returns an HTML string. It does no file I/O and touches no DB --
# cli.py's new `report` command owns writing the string to disk, matching
# every other module's "pure functions in, dataclasses/strings out, the
# CLI decides what to do with it" split.
#
# Deliberately reuses data that already exists rather than adding new
# data collection: RevisionResult (writer.py + critic.py, via
# revision.py) and RoundDiff/SectionDiff (diff.py) already carry
# everything this report needs. This is a rendering pass, same spirit as
# diff.py's own docstring ("adds no new data").

def _render_prose_block(text: str) -> str:
    """Blank-line-separated paragraphs, with '- ' runs collected into a"""
    ...

def _split_headed_sections(text: str) -> list[tuple[str, str]]:
    """Splits text on '## Heading' lines into (heading, body) pairs."""
    ...

def _score_bucket(score: int | None) -> str:
    """CSS class bucket for the score readout / badges. Thresholds are"""
    ...

def _slug(text: str) -> str:
    ...

def report_id(company_name: str, job_title: str, when: datetime.datetime | None=None) -> str:
    """Deterministic-enough ID for a single report, used as both the"""
    ...

def _render_score_dial(score_result: ScoreResult, label: str) -> str:
    ...

def _render_draft_panel(number: str, title: str, body_html: str) -> str:
    ...

def _render_tailored_bullets(tailored_bullets: str) -> str:
    """tailored_bullets already contains its own '## Heading' structure"""
    ...

_CRITIQUE_HEADER_ORDER = ['ATS & Keyword Coverage', 'Unsupported Claims', 'Weak Bullets', 'Weak Summary', 'Cover Letter Critique', 'Overall Recommendation']
def _render_critique(critique_text: str) -> str:
    """Renders critic.py's six substantive headers as cards. The"""
    ...

def _render_diff_line(line: str) -> str:
    ...

def _render_section_diff(section: SectionDiff) -> str:
    ...

def _render_round_history(rounds: list[RevisionRound], round_diffs: list[RoundDiff]) -> str:
    """One <details> block per round after the first, each showing that"""
    ...

_STYLE = '\n:root {\n  --bg: #F6F7F5;\n  --panel: #FFFFFF;\n  --ink: #17231F;\n  --ink-soft: #52625C;\n  --ink-faint: #8B978F;\n  --hairline: #DCE3DE;\n  --accent: #0E6E58;\n  --accent-soft: #E4F1EC;\n  --good: #0E6E58;\n  --good-bg: #E4F1EC;\n  --mid: #B4780F;\n  --mid-bg: #FBEED9;\n  --low: #B0402A;\n  --low-bg: #FBE3DC;\n  --unknown: #8B978F;\n  --unknown-bg: #EDEFEC;\n  --mono: ui-monospace, "SF Mono", "Cascadia Code", "Roboto Mono", Menlo, Consolas, monospace;\n  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;\n}\n* { box-sizing: border-box; }\nbody {\n  margin: 0;\n  background: var(--bg);\n  color: var(--ink);\n  font-family: var(--sans);\n  line-height: 1.55;\n  -webkit-font-smoothing: antialiased;\n}\n.wrap { max-width: 880px; margin: 0 auto; padding: 0 24px 96px; }\n\n/* ---- Header band: lab-requisition styling, mono readout ---- */\n.header {\n  background: var(--ink);\n  color: #F6F7F5;\n  padding: 40px 24px 32px;\n}\n.header__inner { max-width: 880px; margin: 0 auto; }\n.header__id {\n  font-family: var(--mono);\n  font-size: 12.5px;\n  letter-spacing: 0.06em;\n  color: #9FD6C2;\n  text-transform: uppercase;\n  margin-bottom: 14px;\n}\n.header__title { font-size: 28px; font-weight: 650; margin: 0 0 4px; letter-spacing: -0.01em; }\n.header__subtitle { font-size: 15px; color: #C4CCC7; margin: 0 0 24px; }\n.header__meta {\n  display: flex; flex-wrap: wrap; gap: 28px;\n  font-family: var(--mono); font-size: 12px; color: #9FA8A2;\n  border-top: 1px solid #2C3B35; padding-top: 16px;\n}\n.header__meta strong { color: #DDE4E0; font-weight: 600; }\n\n/* ---- Score hero ---- */\n.hero {\n  display: flex; align-items: flex-start; gap: 24px;\n  background: var(--panel); border: 1px solid var(--hairline);\n  border-radius: 4px; padding: 28px; margin: -28px 0 28px;\n  box-shadow: 0 1px 2px rgba(23,35,31,0.04);\n}\n.dial { text-align: center; min-width: 108px; }\n.dial__value {\n  font-family: var(--mono); font-size: 44px; font-weight: 700; line-height: 1;\n}\n.dial__max { font-size: 18px; font-weight: 500; color: var(--ink-faint); }\n.dial__label {\n  margin-top: 8px; font-family: var(--mono); font-size: 11px;\n  letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-faint);\n}\n.dial--good .dial__value { color: var(--good); }\n.dial--mid .dial__value { color: var(--mid); }\n.dial--low .dial__value { color: var(--low); }\n.dial--unknown .dial__value { color: var(--unknown); }\n.dial__rationale { margin: 0; padding-top: 6px; color: var(--ink-soft); font-size: 15px; flex: 1; }\n.hero > .dial__rationale { align-self: center; }\n\n/* ---- Panels ---- */\n.panel {\n  background: var(--panel); border: 1px solid var(--hairline);\n  border-radius: 4px; padding: 24px 28px; margin-bottom: 20px;\n}\n.panel__eyebrow {\n  font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em;\n  text-transform: uppercase; color: var(--accent); margin-bottom: 6px;\n}\n.panel__title { font-size: 19px; margin: 0 0 14px; font-weight: 650; }\n.panel__body p { margin: 0 0 12px; color: var(--ink); }\n.panel__body p:last-child { margin-bottom: 0; }\n.panel__body ul { margin: 0 0 12px; padding-left: 20px; }\n.panel__body li { margin-bottom: 6px; }\n.panel__body .empty { color: var(--ink-faint); font-style: italic; }\n\n.subsection { margin-bottom: 18px; }\n.subsection:last-child { margin-bottom: 0; }\n.subsection h3 {\n  font-size: 13px; font-weight: 650; text-transform: uppercase;\n  letter-spacing: 0.04em; color: var(--ink-soft); margin: 0 0 8px;\n  border-bottom: 1px solid var(--hairline); padding-bottom: 6px;\n}\n.subsection p, .subsection ul { color: var(--ink); }\n\n/* ---- Diff / round history ---- */\n.round {\n  border: 1px solid var(--hairline); border-radius: 4px;\n  margin-bottom: 10px; background: var(--panel);\n}\n.round--base { padding: 14px 18px; }\n.round__head {\n  display: flex; align-items: center; gap: 12px; cursor: pointer;\n  padding: 14px 18px; font-weight: 600; font-size: 14.5px;\n  list-style: none;\n}\n.round__head::-webkit-details-marker { display: none; }\n.round__head::before { content: "\\25B8"; color: var(--ink-faint); font-size: 12px; }\ndetails[open] > .round__head::before { content: "\\25BE"; }\n.round--base .round__head::before { content: ""; }\n.round__score {\n  font-family: var(--mono); font-size: 12px; padding: 2px 8px;\n  border-radius: 3px; margin-left: auto;\n}\n.round__score--good { color: var(--good); background: var(--good-bg); }\n.round__score--mid { color: var(--mid); background: var(--mid-bg); }\n.round__score--low { color: var(--low); background: var(--low-bg); }\n.round__score--unknown { color: var(--unknown); background: var(--unknown-bg); }\n.round__body { padding: 4px 18px 16px; }\n\npre.diff {\n  font-family: var(--mono); font-size: 12.5px; line-height: 1.55;\n  background: #0F1714; color: #DDE4E0; border-radius: 4px;\n  padding: 12px 14px; overflow-x: auto; margin: 0;\n}\n.diffline { display: block; white-space: pre; }\n.diffline--add { color: #8FD9B6; }\n.diffline--del { color: #F0A594; }\n.diffline--hunk { color: #7FB8D6; }\n.diffline--hdr { color: #9FA8A2; }\n.diffline--ctx { color: #C4CCC7; }\n\n/* ---- Job description (collapsed by default) ---- */\ndetails.jd summary {\n  cursor: pointer; font-family: var(--mono); font-size: 12px;\n  letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft);\n  padding: 10px 0;\n}\ndetails.jd .panel__body { white-space: pre-wrap; font-size: 14px; color: var(--ink-soft); }\n\n.raw-critique summary {\n  cursor: pointer; font-family: var(--mono); font-size: 12px;\n  letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft);\n  padding: 4px 0 12px;\n}\n.raw-critique pre {\n  white-space: pre-wrap; font-family: var(--sans); font-size: 14px;\n  color: var(--ink); background: none; margin: 0; padding: 0;\n}\n\n.footer {\n  color: var(--ink-faint); font-size: 12px; font-family: var(--mono);\n  text-align: center; padding-top: 12px;\n}\n\n@media (max-width: 640px) {\n  .hero { flex-direction: column; align-items: center; text-align: center; }\n  .header { padding: 28px 16px 24px; }\n  .panel { padding: 18px; }\n}\n'
def render_posting_report(result: RevisionResult, company_name: str, job_title: str, job_description: str, round_diffs: list[RoundDiff] | None=None, model_routing: dict[str, str] | None=None, generated_at: datetime.datetime | None=None) -> str:
    """Renders one posting's full pipeline output as a self-contained"""
    ...

```

## `src/biohunter/resume_pdf.py`
```python
# Plain, ATS-conventional resume + cover letter PDF export -- the copy
# you'd actually submit for a job, as opposed to report.py's dashboard-
# styled dossier (dark header, score dial, diffs), which is for
# reviewing the pipeline's own output, not for handing to an employer.
#
# Deliberately a SEPARATE, minimal template: no color accents, no score
# readout, single column, plain black-on-white -- closer to what a
# traditional Word-exported resume looks like. Reuses report.py's two
# markdown-shape helpers (_split_headed_sections, _render_prose_block)
# rather than re-implementing the same small "## Heading" / "- item"
# parser twice; this module owns layout/styling only, not text parsing.
#
# PDF rendering uses Playwright's headless Chromium (print-to-PDF), not
# a pure-Python PDF library -- avoids a WeasyPrint-style system-library
# dependency (Pango/Cairo) that's a known pain on macOS without Homebrew.
# New dependency: `pip install playwright && playwright install chromium`
# (one-time browser download; see the module-level NOTE below).
#
# OPEN ITEM, not solved here: WriterDraft carries no candidate
# name/contact info (email, phone, LinkedIn) -- that was never part of
# the Qdrant catalog or the selection branches, all of which only ever
# produce resume BODY content. render_resume_html()/render_cover_letter_html()
# accept optional candidate_name/contact_line params and simply omit the
# header block if they're not given, rather than inventing placeholder
# values. Wire these from wherever you want that data to live (a
# dashboard settings page, an env var, a config file) -- not decided
# here.

_RESUME_STYLE = '\n  * { box-sizing: border-box; }\n  body {\n    margin: 0; padding: 0;\n    font-family: Georgia, "Times New Roman", serif;\n    color: #1A1A1A; font-size: 11pt; line-height: 1.42;\n  }\n  .page { padding: 0.15in 0; }\n  .name { font-size: 20pt; font-weight: 700; margin: 0 0 2px; letter-spacing: 0.01em; }\n  .contact { font-size: 9.5pt; color: #444; margin: 0 0 14px; }\n  .summary { margin: 0 0 16px; }\n  h2 {\n    font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; font-weight: 700;\n    text-transform: uppercase; letter-spacing: 0.06em; color: #1A1A1A;\n    border-bottom: 1px solid #1A1A1A; padding-bottom: 2px; margin: 16px 0 8px;\n  }\n  h2:first-of-type { margin-top: 0; }\n  p { margin: 0 0 8px; }\n  ul { margin: 0 0 8px; padding-left: 18px; }\n  li { margin-bottom: 4px; }\n  .empty { display: none; }\n'
_COVER_LETTER_STYLE = '\n  * { box-sizing: border-box; }\n  body {\n    margin: 0; padding: 0;\n    font-family: Georgia, "Times New Roman", serif;\n    color: #1A1A1A; font-size: 11.5pt; line-height: 1.55;\n  }\n  .page { padding: 0.15in 0; }\n  .letterhead-name { font-size: 15pt; font-weight: 700; margin: 0 0 2px; }\n  .letterhead-contact { font-size: 9.5pt; color: #444; margin: 0 0 28px; }\n  p { margin: 0 0 12px; }\n'
def render_resume_html(draft: WriterDraft, candidate_name: str='', contact_line: str='') -> str:
    """tailored_bullets already carries its own '## Heading' structure"""
    ...

def render_cover_letter_html(draft: WriterDraft, candidate_name: str='', contact_line: str='') -> str:
    ...

def html_to_pdf_bytes(html_str: str) -> bytes:
    """Renders one HTML string to PDF bytes via headless Chromium."""
    ...

```

## `src/biohunter/revision.py`
```python
# Revision loop: Writer -> Critic -> Writer Revision -> Critic -> ... for a
# configurable number of rounds, then hands off to Human Review (ADR-0006
# Phase 2 item #2, per the 2026-08-06 handoff).
#
# This module is intentionally thin -- it owns only the looping and the
# history record. All the real work (verbatim-catalog selection, the
# no-invented-facts guarantee, the critique prompt) already lives in
# writer.py/selection.py/critic.py; run_revision_loop() just calls them
# repeatedly, feeding each round's critique into the next round's
# generate_draft() call via the critique_feedback param those modules
# already accept.
#
# Like critic.py, this stays DB/persistence-agnostic on purpose -- no
# `awaiting_review` status writes, no storage. A caller (CLI today, a
# future Captain auto-trigger path later) decides what to persist and
# when; this module just produces the final draft + critique + full
# round-by-round history so the caller has everything it needs to persist
# however it wants.

CRITIC_ROLE = 'critic_review'
class RevisionRound:
    round_number: int
    draft: WriterDraft
    critique: str

class RevisionResult:
    final_draft: WriterDraft
    final_critique: str
    rounds: list[RevisionRound] = field(default_factory=list)

def run_revision_loop(llm: LLMClient, company_name: str, job_title: str, job_description: str, revision_rounds: int=1, think: bool=False) -> RevisionResult:
    """Generates a first draft, critiques it, then re-generates and"""
    ...

```

## `src/biohunter/scorer.py`
```python
# Scorer agent: one blind-judgment LLM call producing a job-FIT score
# (postings.score / postings.score_rationale) for a posting BEFORE any
# resume gets generated for it -- the "which of these 693 postings are
# worth generating for" triage step the 2026-08-09 handoff calls out as a
# separate, real piece of work from Critic's resume-QUALITY score
# (drafts.final_score). Per the pipeline diagram (Scout -> Scorer -> Writer
# -> Critic -> Human Review), this is the step that's been missing.
#
# Deliberately NOT the same shape as critic.py's critique_draft(): Critic
# judges an already-written draft against a job description. Scorer judges
# a job POSTING against the CANDIDATE -- their existing summary/skills/
# career-history/education catalog (the same Qdrant `resume_content`
# collection Writer draws from, via qdrant.py + selection.py's own catalog
# helpers) plus their stated location/title preferences
# (config/search_criteria.yaml) -- with no draft anywhere in the loop. Same
# "one prompt, one call, return structured text" spirit as critic.py,
# though: there's nothing to SELECT here (no verbatim-choice constraint
# selection.py's branches enforce), just a judgment to make, so it reuses
# critic.py's own ScoreResult / parse_score() rather than inventing a
# second "SCORE: N -- rationale" parser that has to be kept in sync with
# the first.
#
# CORRECTED against real source (writer.py/selection.py/qdrant.py, added
# 2026-08-09 after this module's first draft was written blind against an
# AST outline only):
#   - section_type values are "professional_summary" and "key_skills", not
#     "summary"/"skills" -- the first draft's guessed names would have
#     returned zero Qdrant points every time, silently, since
#     fetch_by_section_type() has no fallback and no error on an empty
#     match.
#   - key_skills payloads carry only `text` (see select_skills() in
#     selection.py) -- no `label` field, unlike the professional_summary
#     catalog. Running them through load_catalog()/CatalogEntry the same
#     way as the summary catalog produced blank labels; skills are now
#     read as a flat text list instead, matching select_skills()'s own
#     approach.
#   - llm.complete() takes `think` as a required-in-spirit kwarg -- per
#     selection.py's own docstring, omitting it does NOT behave like
#     think=False, it runs 4-6x slower like think=True. The first draft
#     omitted it entirely. Fixed: score_posting() now takes `think` and
#     always passes it through explicitly, same convention every other
#     LLM-calling function in this codebase follows.
#
# SCOPE LIMIT, stated explicitly rather than solved by omission (per this
# project's own working style -- see the 2026-08-09 handoff's "Scorer vs
# Critic score" section): schema.sql's own postings.score comment describes
# fit to "the candidate, location, seniority, visa, salary, preferences."
# Visa status and salary expectations are NOT modeled anywhere in this
# codebase today -- not in search_criteria.yaml, not in Qdrant, not in any
# config file. This version scores fit on role/skill/background alignment
# (semantic, against the candidate's Qdrant catalog), location (against
# search_criteria.yaml's location_include/exclude), and seniority (inferred
# from title/description text). Visa and salary are NOT scored -- there is
# no data to score them against yet. If those matter, they need a real new
# config field (most likely a search_criteria.yaml addition) before Scorer
# can use them; not guessed here.
#
# CONFIG DEPENDENCY, confirmed against real roles.yaml: no `scorer_fit`
# entry exists yet. LLMClient resolves role names purely from
# config/roles.yaml, so this will fail with a lookup error until one is
# added. Every existing role in your roles.yaml routes through Ollama
# (gemma4:12b-mlx or qwen2.5:14b) except the still-unused mlx_smoke_test --
# there is no cloud-routed role active in this file to mirror for a
# "quality-sensitive" default the way the earlier draft assumed. Suggested
# addition, consistent with your file's own local-first pattern (add to
# config/roles.yaml, not done here since it's your file to own):
#
#     scorer_fit:
#       provider: ollama
#       model: qwen2.5:14b       # matches scout_summarizer's model -- a
#                                 # cheap/fast local model is appropriate
#                                 # here, this runs once per posting at
#                                 # triage scale (hundreds of calls)
#       base_url: http://localhost:11434
#
# INVOCATION, scoped deliberately: like run_scout(), this is driven from the
# CLI (`biohunter score-postings`), not from the dashboard. The dashboard
# only reads and filters/sorts on the postings.score column this populates
# -- it does not trigger scoring itself, matching the existing precedent
# that Scout also only ever runs from the CLI, never from a dashboard
# button.

SCORER_ROLE = 'scorer_fit'
SCORER_INSTRUCTION = "You are a candid, detail-oriented career advisor helping a candidate triage a large batch of job postings BEFORE they spend time generating a tailored resume for any of them. You are given the candidate's actual background (summary, skills, career history, education) and their stated location/title preferences, plus one job posting. Your job is to judge how good a FIT this posting is for this candidate -- NOT how good a resume could be written for it (that is a separate, later step). Be direct: a senior-only posting for a candidate with no matching seniority, or a posting far outside stated location preferences, should score low even if the subject-matter skills overlap well.\n\nConsider, in this order of importance: (1) role/skill/background alignment against the candidate's actual profile below -- don't assume relevance from the job title alone; (2) location fit against the candidate's stated preferences; (3) seniority fit (junior/mid/senior/staff+) based on the posting's title and description.\n\nDo NOT attempt to judge visa sponsorship or salary fit -- you have no data on either for this candidate; ignore those dimensions entirely rather than guessing.\n\nRespond with your assessment as one short paragraph, then end with exactly this line and nothing after it:\nSCORE: <integer 1-10> -- <one-sentence rationale>"
def _build_candidate_profile_text() -> str:
    """Fetches the candidate's summary/skills/career-history/education"""
    ...

def score_posting(llm: LLMClient, company_name: str, job_title: str, location: str | None, job_description: str, criteria: SearchCriteria, think: bool=False) -> ScoreResult:
    """One blind fit-judgment call for one posting. Returns critic.py's"""
    ...

```

## `src/biohunter/scout/__init__.py`
```python
```

## `src/biohunter/scout/detector.py`
```python
STALE_AFTER_DAYS = 30
class ScoutResult:
    company_name: str
    strategy: str
    new_postings: int
    total_postings: int
    error: str | None = None

def _clean_description(raw: str | None) -> str | None:
    """Strips HTML down to plain text. ATS public APIs conventionally"""
    ...

def _get_or_create_company_id(conn, company: CompanyConfig) -> int:
    ...

def _upsert_postings(conn, company_id: int, postings: list[RawPosting]) -> int:
    """Insert new postings, refresh last_seen_at on existing ones. Returns count of new postings."""
    ...

def _mark_stale_postings(conn, company_id: int, run_time: datetime.datetime) -> int:
    """Mark postings not seen in this company's last STALE_AFTER_DAYS worth"""
    ...

def run_scout(limiter: RateLimiter | None=None, db_path: str | None=None) -> list[ScoutResult]:
    """One Scout pass over every active company in the registry."""
    ...

```

## `src/biohunter/scout/ratelimit.py`
```python
MIN_SECONDS_BETWEEN_REQUESTS_SAME_DOMAIN = 2.0
_USER_AGENT = 'BioHunter/0.1 (personal job-search tool; contact: set-your-email-here)'
class RateLimiter:
    def __init__(self, min_interval: float=MIN_SECONDS_BETWEEN_REQUESTS_SAME_DOMAIN):
        ...

    def wait_for_domain(self, url: str) -> None:
        ...

    def allowed_by_robots(self, url: str) -> bool:
        """Only meaningful for the fallback scraper -- ATS API calls hit a"""
        ...


```

## `src/biohunter/scout/scraper.py`
```python
def fetch_page(url: str, limiter: RateLimiter) -> str:
    ...

def content_hash(html: str) -> str:
    ...

def extract_postings(html: str, css_selector: str, base_url: str) -> list[RawPosting]:
    """Structured scrape: css_selector should match anchor tags (or elements"""
    ...

def check_for_change(html: str, previous_hash: str | None) -> tuple[bool, str]:
    """Returns (changed, new_hash). If css_selector-based extraction later"""
    ...

```

## `src/biohunter/selection.py`
```python
logger = logging.getLogger(__name__)
_FENCE_RE = re.compile('^```(?:json)?\\s*|```\\s*$', re.MULTILINE)
def strip_fences(text: str) -> str:
    """Ports stripFences() from every n8n "parse X selection" node —"""
    ...

def parse_json_response(text: str, default: dict) -> dict:
    """Ports the try/catch-with-default pattern every n8n parse node"""
    ...

class CatalogEntry:
    label: str
    text: str
    alignment_text: str = ''

def load_catalog(payloads: list[dict]) -> list[CatalogEntry]:
    """Turns raw Qdrant payloads into CatalogEntry objects. Every"""
    ...

def _catalog_text(catalog: list[CatalogEntry]) -> str:
    ...

class VariantSelection:
    label: str
    text: str
    alignment_text: str = ''

def select_variant(llm: LLMClient, role: str, instruction: str, job_description: str, catalog: list[CatalogEntry], branch_name: str, think: bool=False, critique_feedback: str | None=None) -> VariantSelection:
    """The shape shared by summary/intro/story/impact/gratitude: show the"""
    ...

SUMMARY_INSTRUCTION = 'You are selecting exactly ONE pre-written resume summary paragraph that best matches this job description. Choose one label from the catalog below verbatim -- do not edit, rephrase, merge, or invent.'
INTRO_INSTRUCTION = 'You are selecting exactly ONE pre-written cover letter introduction paragraph that best matches this job description. Choose one label from the catalog below verbatim -- do not edit, rephrase, merge, or invent.'
STORY_INSTRUCTION = 'You are selecting exactly ONE pre-written cover letter story that best matches this job description. Choose one label from the catalog below verbatim -- do not edit, rephrase, merge, or invent.'
IMPACT_INSTRUCTION = 'You are selecting exactly ONE pre-written cover letter forward-looking impact statement that best matches this job description. Choose one label from the catalog below verbatim -- do not edit, rephrase, merge, or invent.'
GRATITUDE_INSTRUCTION = 'You are selecting exactly ONE pre-written cover letter closing/gratitude paragraph that best matches this job description. Choose one label from the catalog below verbatim -- do not edit, rephrase, merge, or invent.'
HEADING_INSTRUCTION = 'You are selecting which Professional Experience headings are relevant to this job description. You may select headings from different resume flavors (e.g. an AI role and an LC-MS role can both draw headings) -- cross-flavor hybrid combinations are allowed and expected when justified. Select only from the exact heading catalog below, do not invent new headings.'
def select_headings(llm: LLMClient, role: str, job_description: str, heading_payloads: list[dict], branch_name: str='heading pass 1', think: bool=False, critique_feedback: str | None=None) -> list[str]:
    """heading_payloads come from"""
    ...

BULLET_INSTRUCTION = 'You are selecting the most relevant bullets under each Professional Experience heading below, for this job description. Copy selected bullets VERBATIM -- do not edit, merge, rephrase, or invent new bullets. You do not need to select bullets from every heading -- but every heading listed below MUST still appear as a key in your JSON response. If you don\'t want any bullets from a heading, give it an empty array, e.g. "Some Heading": []. Never omit a heading\'s key entirely -- a heading present with an empty array means \'no relevant bullets\'; a missing key is not a valid way to express that.'
class BulletSelection:
    validated_selection: dict[str, list[str]] = field(default_factory=dict)
    tailored_bullets: str = ''

def select_bullets(llm: LLMClient, role: str, job_description: str, selected_headings: list[str], bullet_payloads: list[dict], branch_name: str='bullet pass 2', think: bool=False, critique_feedback: str | None=None) -> BulletSelection:
    """bullet_payloads come from"""
    ...

SKILLS_INSTRUCTION = 'You are selecting the individual Key Skills bullets most relevant to this job description, from the flat catalog below. Copy selected items VERBATIM -- do not edit, merge, or invent. Do not pull in unrelated skills just because they share a category with a relevant one.'
class SkillsSelection:
    validated_selection: list[str] = field(default_factory=list)
    tailored_skills: str = ''

def select_skills(llm: LLMClient, role: str, job_description: str, skill_payloads: list[dict], branch_name: str='skills', think: bool=False, critique_feedback: str | None=None) -> SkillsSelection:
    """skill_payloads come from"""
    ...

ALWAYS_FULL_SECTION_TYPES = ['career_history', 'education', 'patents', 'honors_and_special_awards', 'publications']
class AlwaysFullSections:
    career_history: str = ''
    education: str = ''
    patents: str = ''
    honors: str = ''
    publications: str = ''

def load_always_full_sections(payloads: list[dict]) -> AlwaysFullSections:
    """payloads come from"""
    ...

def stitch_cover_letter(llm: LLMClient, role: str, job_title: str, company_name: str, job_description: str, intro: VariantSelection, story: VariantSelection, impact: VariantSelection, gratitude: VariantSelection, think: bool=False, critique_feedback: str | None=None) -> str:
    """think: see select_variant()'s docstring."""
    ...

class DraftResume:
    tailored_summary: str
    tailored_bullets: str
    cover_letter: str

def assemble_draft(summary_text: str, bullets_markdown: str, skills_markdown: str, always: AlwaysFullSections, cover_letter: str) -> DraftResume:
    ...

```

## `src/biohunter/writer.py`
```python
# Orchestrates one full Writer pass for a single job posting: runs every
# n8n-equivalent selection branch against Qdrant + LLMClient, stitches the
# cover letter, and assembles the final draft resume + cover letter text.
#
# This is the native replacement for the n8n workflow's node graph from
# "split jobs" through "assemble draft resume" (see ADR-0006 build order,
# step 1). ATS scoring, critique, and the human-approval gate are steps
# 2/3 — not built here yet; generate_draft() stops exactly where n8n's
# "assemble draft resume" node did.

SELECTION_ROLE = 'writer_selection'
class WriterDraft:
    company_name: str
    job_title: str
    tailored_summary: str
    tailored_bullets: str
    cover_letter: str

def generate_draft(llm: LLMClient, company_name: str, job_title: str, job_description: str, think: bool=False, critique_feedback: str | None=None) -> WriterDraft:
    """Runs the full 8-branch selection pipeline for one posting and"""
    ...

```
