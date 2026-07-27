# BioHunter — Handoff Prompt (Phase 1 → Phase 2 transition)

Paste this whole document as the first message in a new chat to continue work with full context.

---

## Project summary

BioHunter is a self-hosted, multi-agent job-hunting system for Bay Area
biotech roles. Full design: `docs/design/biotech-job-hunter-design.md`.
Key architectural decisions are recorded in `docs/adr/0001-*.md` and
`docs/adr/0002-*.md` — **read those before proposing changes to
scoring/resume logic or adding new agents/frameworks.** In short: Scorer
and Writer delegate to an existing external n8n + Hermes Agent pipeline
rather than reimplementing scoring; this is single-user and intentionally
not built for multi-tenant/24-7 scale.

## Stack

Python (src-layout package `biohunter`), libsql-experimental (Turso/SQLite-
compatible), requests + BeautifulSoup for scraping, pytest for tests.
macOS (M4, 24GB), VS Code, venv-based dev environment (`.venv`).

## Current state: Phase 1 (Scout + storage) — mostly complete

### What exists and is tested (7 passing pytest tests)
- `schema.sql` — companies/postings/applications/contacts/outreach_emails/
  conferences/run_log tables.
- `src/biohunter/db.py` — `get_connection()` defaults to a local
  `data/biohunter.db` file; becomes a Turso-synced embedded replica if
  `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` env vars are set. **Not yet
  switched over to real Turso — still running local-only.** User has a
  free-tier Turso account ready to use whenever.
- `src/biohunter/ats/` — adapters for **Greenhouse, Lever, Ashby, Workday**.
  Workday adapter (`workday.py`) hits the internal CXS JSON endpoint
  (undocumented but stable in practice); `ats_slug` format is
  `"{subdomain}/{site}"`, e.g. `"roche.wd3/ROG-A2O-GENE"` for Genentech.
- `src/biohunter/scout/scraper.py` — fallback scraper for self-hosted
  career pages: sha256 content-hash diff detection + CSS-selector-based
  posting extraction. **Known limitation: plain `requests` doesn't render
  JS.** At least one target company (Astellas) has a JS-rendered careers
  site (Phenom/NLX-based) that this scraper likely can't handle — may
  need a Playwright-based fallback path eventually (Playwright is already
  in the planned stack for Phase 4 Filler, so there's a case for
  introducing it earlier just for Scout on JS-heavy sites).
- `src/biohunter/scout/ratelimit.py` — per-domain min-interval throttle +
  robots.txt check (fail-open if robots.txt unreachable).
- `src/biohunter/scout/detector.py` — orchestrates Scout: ATS API first,
  fallback scrape otherwise; upserts on `(company_id, url)`; one
  company's failure never aborts the run (ADR-0001: flag, don't silently
  fail).
- `src/biohunter/detect_ats.py` — **auto-detection helper**: given a list
  of `{name, careers_url}`, fetches each page, fingerprints
  Greenhouse/Lever/Ashby/Workday from the resolved URL + HTML (catches
  iframe-embedded boards too), writes/merges results into
  `config/companies.yaml`. Companies already configured are left alone
  unless `--force`.
- `src/biohunter/cli.py` — `run-scout` and `list-postings` subcommands.
  `list-postings` filters by title keywords AND location, sourced from
  `config/search_criteria.yaml` by default, overridable via
  `--include/--exclude/--location/--company` flags.
- `config/search_criteria.yaml` (gitignored, `.example.yaml` checked in) —
  **this is the intentionally swappable piece**: location + title
  include/exclude lists live here, not in code. Confirmed design intent:
  repointing the whole system at a different location/domain (e.g.
  "Vietnam, AI automation roles") should require editing only this file
  + `companies.yaml`, zero code changes. This has NOT been stress-tested
  with a real second profile yet — if the user wants to actually run two
  concurrent searches (not just swap one), they'll need a `--profile`
  flag that picks a named config+db pair (discussed, not built).

### Company registry status (`config/companies.yaml`, gitignored)
Working (`ats_type: workday`, confirmed via live `run-scout`):
- **Genentech** — `roche.wd3/ROG-A2O-GENE` — 227 postings pulled successfully.
- **Gilead Sciences** — user configured this one independently (not in my
  original 10-company research pass) — also on Workday, 40 postings pulled
  successfully. Good independent confirmation the Workday adapter is solid.

Needs work — **Denali Therapeutics** currently errors: "No ats_type and no
css_selector configured." Needs either:
(a) confirm its actual ATS (my research found `denalitherapeutics.com/careers/`
but couldn't confirm the underlying platform — worth re-running
`detect_ats.py` against it, or checking manually), or
(b) a `css_selector` for fallback scraping if it's a fully custom site.

Remaining 8 from the original target list (not yet added/confirmed):
Astellas (JS-rendered, likely needs Playwright — see above), BioMarin
Pharmaceutical (**on Jobvite** — `jobs.jobvite.com/biomarin/jobs` — no
adapter built for Jobvite yet), Amgen (large custom site, likely no open
API), 10x Genomics, Exelixis, Guardant Health, Mammoth Biosciences, Nurix
Therapeutics, Scribe Therapeutics — ATS platform unconfirmed for these
last 5, worth running through `detect_ats.py` first.

**Pattern observed so far**: smaller/newer biotechs tend to land on
Greenhouse/Lever/Ashby; large/established pharma tends to run custom or
enterprise ATS (Jobvite, Phenom, Taleo-style) with no open API — expect a
meaningful fraction of any large-company list to need `css_selector` +
fallback scraping rather than a clean adapter hit.

### Known gaps / open decisions for the next session
1. **Denali Therapeutics** — unblock this one first, it's the active error.
2. **Jobvite adapter** — worth building if BioMarin (or others) confirm
   Jobvite as their ATS; same shape as the other four adapters in
   `src/biohunter/ats/`.
3. **JS-rendered fallback scraping** (Astellas and similar) — current
   scraper can't handle these; decide whether to pull Playwright forward
   from Phase 4 for this specific case, or accept manual/skip for such
   companies in Phase 1.
4. **Turso migration** — user has a free-tier account ready; not yet
   switched from local SQLite file. Low-risk, whenever convenient.
5. **`--profile` flag** — not built; only relevant if the user wants
   concurrent multi-search (e.g. biotech + a second unrelated search)
   rather than swapping one config in place.

### Explicitly NOT done yet (Phase 2, per ROADMAP.md — do not build early)
- n8n webhook client for scoring
- n8n webhook client for resume assembly
- LLM call for cover letter + tailoring rationale
- Critic blind-review step (ADR-0002)
- Weekly cloud token/cost log (ADR-0002)

## How to pick this up
1. Read `docs/adr/0001-*.md` and `0002-*.md` if not already loaded — they
   constrain what NOT to reimplement (scoring, resume assembly) and what
   NOT to over-build (subscription tiers, multi-user, always-on scale).
2. Run `pytest tests/ -v` first to confirm the current state is still green
   (7 tests) before making changes.
3. Fix Denali Therapeutics, then work through the remaining 8 companies
   via `detect_ats.py`, adding adapters/selectors as needed.
4. Once the company registry is stable, move to Phase 2 per `ROADMAP.md`.

---
*(End of handoff — paste everything above this line into a new chat.)*
