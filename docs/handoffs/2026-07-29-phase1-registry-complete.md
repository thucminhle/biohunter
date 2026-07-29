# BioHunter — Handoff Prompt (Phase 1 wrap-up → Phase 2)

Paste this whole document as the first message in a new chat to continue work with full context.

---

## Project summary

BioHunter is a self-hosted, multi-agent job-hunting system for Bay Area
biotech roles. Full design: `docs/design/biotech-job-hunter-design.md`.
Key architectural decisions: `docs/adr/0001-*.md` and `docs/adr/0002-*.md`
— **read those before proposing changes to scoring/resume logic or adding
new agents/frameworks.** In short: Scorer and Writer delegate to an
existing external n8n + Hermes Agent pipeline rather than reimplementing
scoring; this is single-user and intentionally not built for
multi-tenant/24-7 scale.

## Stack

Python (src-layout package `biohunter`), libsql-experimental (Turso/SQLite-
compatible, currently running local-file-only, not yet switched to real
Turso), requests + BeautifulSoup for scraping, pytest for tests. macOS
(M4, 24GB), VS Code, venv-based dev environment (`.venv`). User has a
free-tier Turso account not yet wired up (low priority, whenever).

## Current state: Phase 1 (Scout + storage) — code-complete, registry in progress

### What exists and is tested (8 passing pytest tests)
- `schema.sql` — companies/postings/applications/contacts/outreach_emails/
  conferences/run_log tables. `postings.status` supports
  new|scored|applied|rejected|stale.
- `src/biohunter/db.py` — `get_connection(local_path=None)` defaults to
  local `data/biohunter.db`; becomes a Turso-synced embedded replica if
  `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` env vars are set.
- **Six ATS adapters** in `src/biohunter/ats/`, all registered in
  `REGISTRY` (`ats/__init__.py`):
  - `greenhouse.py`, `lever.py`, `ashby.py` — standard public JSON APIs.
  - `workday.py` — hits the internal CXS JSON endpoint. `ats_slug` format
    `"{subdomain}/{site}"`, and supports MULTIPLE sites per company
    comma-separated (`"dnli.wd1/Discovery,Development,Corporate_Positions"`)
    since some companies (Denali) split postings across several separate
    Workday career sites rather than one unified site.
  - `jobvite.py` — Jobvite's real API needs a customer key, so this
    scrapes the plain server-rendered `jobs.jobvite.com/{slug}/jobs` HTML
    page directly instead. Known limitation: categories with many postings
    paginate via a "Show More" link that isn't followed, so large
    categories may undercount.
  - `jobsyn.py` — DirectEmployers' National Labor Exchange (jobsyn.org)
    backend, common among **federal-contractor** employers for OFCCP
    compliance postings (look for `"federal_contractor": true` in the raw
    job data as a tell). Unusual among all the adapters: company-scoped
    entirely by HTTP headers (`Origin`/`Referer`/`X-Origin` set to the
    career site's own domain), NOT by anything in the URL. `ats_slug` is
    just that domain, e.g. `"astellascareers.jobs"`. **This backend is
    worth checking for other large/federal-contractor companies on the
    target list (Amgen especially) before assuming a new adapter is
    needed** — same DevTools Network-tab technique that found it for
    Astellas will confirm or rule it out quickly.
- `src/biohunter/scout/scraper.py` — fallback scraper for fully custom
  self-hosted career pages with no adapter: sha256 content-hash diff
  detection + CSS-selector-based extraction. Known limitation: plain
  `requests` doesn't render JS, so JS-heavy career sites (confirmed
  problem for at least one target company previously) need the DevTools
  Network-tab trick (find the underlying JSON API call, as done for
  Astellas) rather than a css_selector, or eventually a Playwright-based
  path.
- `src/biohunter/scout/ratelimit.py` — per-domain min-interval throttle +
  robots.txt check.
- `src/biohunter/scout/detector.py` — orchestrates Scout: ATS API first,
  fallback scrape otherwise; upserts on `(company_id, url)`; one
  company's failure never aborts the run. **New this round**:
  `_mark_stale_postings()` — after any SUCCESSFUL fetch for a company
  (never after a failed one), postings not re-seen in `STALE_AFTER_DAYS`
  (30) get `status = 'stale'`. Postings already `applied`/`rejected` are
  protected and never overwritten.
- `src/biohunter/detect_ats.py` — auto-detection helper: given
  `{name, careers_url}` pairs, fetches each page, fingerprints
  Greenhouse/Lever/Ashby/Workday (not yet Jobvite/Jobsyn — see gaps
  below) from the resolved URL + HTML, writes/merges into
  `config/companies.yaml`.
- `src/biohunter/cli.py`:
  - `run-scout` — one Scout pass, prints per-company summary, logs to
    `run_log`.
  - `list-postings` — filters by title keywords AND location, sourced
    from `config/search_criteria.yaml` by default
    (`--include/--exclude/--location/--company` override per-run).
    **Excludes `stale` postings by default now; `--include-stale` shows
    them anyway.**
- `config/search_criteria.yaml` (gitignored, `.example.yaml` checked in)
  — the intentionally swappable piece: location + title include/exclude
  lists live here, not in code, so repointing at a different
  location/domain search needs only this file + `companies.yaml` edited,
  zero code changes. Confirmed as a design goal; not yet stress-tested
  with an actual second concurrent profile (would need a `--profile` flag
  to pick a named config+db pair, not built).

### Company registry status (`config/companies.yaml`, gitignored) — LIVE, CONFIRMED WORKING
As of the last successful `run-scout`:
- **Genentech** — Workday, `roche.wd3/ROG-A2O-GENE` — 231 postings.
- **Gilead Sciences** — Workday (user-added independently) — 40 postings.
- **Denali Therapeutics** — Workday, multi-site
  `dnli.wd1/Discovery,Development,Corporate_Positions,Internships` — 17
  postings.
- **Astellas** — Jobsyn/NLX, `astellascareers.jobs` — 89 postings.
- **BioMarin Pharmaceutical** — Jobvite, `biomarin` — 128 postings.

**Total: 505 postings tracked, 0 errors on last run.**

### Remaining from the original 10-company target list — NOT YET ADDED
Amgen, 10x Genomics, Exelixis, Guardant Health, Mammoth Biosciences,
Nurix Therapeutics, Scribe Therapeutics. None of these have been
researched yet in this project (the BioMarin/Astellas/Denali work above
covered the ones that turned out to need non-trivial ATS detection work;
these seven are unstarted). Suggested approach for the next session:
1. Run each through `detect_ats.py` first (catches Greenhouse/Lever/
   Ashby/Workday automatically).
2. For Amgen specifically: check whether it's on the same Jobsyn/NLX
   backend as Astellas before assuming a custom scrape is needed (large
   federal contractors are the pattern that predicts Jobsyn usage).
3. For whatever's left, use the DevTools Network-tab technique (Network
   tab → Fetch/XHR → reload/search → find the JSON-returning request →
   share the request URL + headers + response shape) rather than
   guessing at scrapers for JS-rendered sites.

### Known process issue to watch for
Incremental patch tarballs were sent turn-by-turn across a long session,
and at least one failed to actually get extracted into the user's local
repo (the `list-postings` command silently went missing for a while as a
result). **A full-codebase tarball was sent at the end of the last
session** (`biohunter-full-current.tar.gz`) specifically to resync
everything in one shot, excluding the user's personal
`companies.yaml`/`search_criteria.yaml`. If odd "missing command" or
"missing feature" reports come up again, suspect a partial-apply issue
first — have the user run `git status` / diff after extracting anything,
and consider defaulting to full-codebase tarballs over incremental
patches for the rest of this project.

### Explicitly NOT done yet (Phase 2, per ROADMAP.md — do not build early)
- n8n webhook client for scoring
- n8n webhook client for resume assembly
- LLM call for cover letter + tailoring rationale
- Critic blind-review step (ADR-0002)
- Weekly cloud token/cost log (ADR-0002)

## How to pick this up
1. Read `docs/adr/0001-*.md` and `0002-*.md` if not already loaded.
2. Run `pytest tests/ -v` first to confirm the current state is still
   green (8 tests) before making changes.
3. Work through the remaining 7 companies (see above), using
   `detect_ats.py` first and the DevTools technique as fallback.
4. Once the registry is stable and Scout's been running cleanly for a
   few days, move to Phase 2 per `ROADMAP.md`.

---
*(End of handoff — paste everything above this line into a new chat.)*
