# BioHunter — Handoff Prompt (Phase 1 registry: 8/10 live, ADR-0003 drafted)

Paste this whole document as the first message in a new chat to continue work with full context.

---

## Project summary

BioHunter is a self-hosted, multi-agent job-hunting system for Bay Area
biotech roles. Full design: `docs/design/biotech-job-hunter-design.md`.
Key architectural decisions: `docs/adr/0001-*.md`, `0002-*.md`, and
**new this session: `0003-*.md`** — **read all three before proposing
changes to scoring/resume logic, adding new agents/frameworks, or building
ATS discovery tooling.** In short: Scorer and Writer delegate to an
existing external n8n + Hermes Agent pipeline rather than reimplementing
scoring (ADR-0001); this is single-user and intentionally not built for
multi-tenant/24-7 scale (ADR-0002); and ATS discovery for companies the
six existing adapters can't handle will be automated via a headless
browser rather than done by hand per-company, going forward (ADR-0003 —
not yet built, see below).

## Stack

Python (src-layout package `biohunter`), libsql-experimental (Turso/SQLite-
compatible, currently running local-file-only, not yet switched to real
Turso), requests + BeautifulSoup for scraping, pytest for tests. macOS
(M4, 24GB), VS Code, venv-based dev environment (`.venv`). User has a
free-tier Turso account not yet wired up (low priority, whenever).
**Playwright is not yet installed** — it's a new dependency introduced by
ADR-0003, not yet added to `requirements.txt`.

## Current state: Phase 1 (Scout + storage) — registry now 8/10, code still green

### What exists and is tested (8 passing pytest tests — confirmed green this session)
Unchanged from last handoff — see `docs/handoffs/2026-07-29-phase1-registry-complete.md`
for the full adapter-by-adapter description (schema, db.py, all six ATS
adapters, scraper.py, ratelimit.py, detector.py, detect_ats.py, cli.py).
Nothing in the codebase itself changed this session — this was a pure
registry-research + planning session, no code was written or modified.

### Company registry status (`config/companies.yaml`, gitignored) — 8/10 LIVE
As of the last successful `run-scout` this session (10 companies checked,
172 new postings, **317 total tracked**):

| Company | ATS | `ats_slug` | Status |
|---|---|---|---|
| Genentech | Workday | `roche.wd3/ROG-A2O-GENE` | ✅ live (236 total) |
| Gilead Sciences | Workday | `gilead.wd1/gileadcareers` | ✅ live (40 total) |
| Denali Therapeutics | Workday (multi-site) | `dnli.wd1/Discovery,Development,Corporate_Positions,Internships` | ✅ live (17 total) |
| Astellas | Jobsyn/NLX | `astellascareers.jobs` | ✅ live (87 total) |
| BioMarin Pharmaceutical | Jobvite | `biomarin` | ✅ live (125 total) |
| **Amgen** (new) | Workday | `amgen.wd1/Careers` | ✅ live (40 total) |
| **Guardant Health** (new) | Workday | `gh.wd1/gh` | ✅ live (73 total) |
| **Mammoth Biosciences** (new) | Lever | `mammothbiosci` | ✅ live (2 total) |
| **Nurix Therapeutics** (new) | Greenhouse | `nurix` | ✅ live (19 total) |
| **Scribe Therapeutics** (new) | — | — | ❌ errors every run (see below) |

**Original 10-company target list is now fully attempted — 8 live, 2 blocked.**

### The 2 remaining problem companies — NOT a Jobsyn/known-adapter situation
Both were researched this session via web search/fetch (no browser
available in this chat), which is why neither is resolved yet — these
need an actual browser with DevTools, which only the user can drive.

- **Exelixis** — no ATS signature found at all (Greenhouse/Lever/Ashby/
  Workday/Jobvite/Jobsyn all ruled out). Career site is WordPress-based
  with its own filterable job search (`/careers/job-openings/?keyword=&
  location=&employment_type=&departments=&view_all=true`) — almost
  certainly backed by a JSON endpoint the filter UI calls client-side,
  but that's invisible to a plain fetch. **Needs DevTools Network-tab
  check**, same technique used for Astellas in the previous session.
- **Scribe Therapeutics** — **currently in `companies.yaml` with a wrong
  guess**: `ats_type: greenhouse`, `ats_slug: scribetherapeutics`. This
  404s on every `run-scout` (harmless — detector.py's per-company
  isolation means the other 9 still complete fine, but it's noise in the
  output). The real careers page is `scribetx.com/careers`, a Webflow
  site whose "Openings" section is a client-side-rendered placeholder —
  same category as Exelixis. **Needs DevTools Network-tab check** before
  the `companies.yaml` entry can be corrected.

**10x Genomics was also researched but is a separate, bigger case — see
ADR-0003 below.** It's not just a "needs DevTools" company like the two
above; it's on **Eightfold.ai**, a 7th ATS platform not covered by any
existing adapter or `detect_ats.py` signature. Confirmed via direct page
fetch (footer reads "Powered by eightfold.ai"; the Greenhouse-looking PDF
link in its EEOC form was a red herring, not a real signature).

### New this session: ADR-0003 drafted (not yet implemented)
`docs/adr/0003-automate-ats-discovery-for-scale.md` — decision to build
`discover_ats.py`, a headless-Playwright network-sniffing tool that
automates the DevTools technique instead of a human doing it per company,
since "hundreds of companies" (the user's stated scaling direction) makes
manual DevTools-per-company unworkable. Key points for the next session:

- **`discover_ats.py` is NOT the same tool as `detect_ats.py`.**
  `detect_ats.py` (existing) does fast plain-HTTP signature matching
  against *known* ATS patterns — no browser, no JS execution.
  `discover_ats.py` (new, not yet built) is the fallback when
  `detect_ats.py` finds nothing: it launches a real headless browser,
  captures every XHR/fetch response, and heuristically ranks which ones
  look job-shaped, for human review.
- Distinguishes two failure categories on purpose: (1) JS-rendered pages
  with a real API underneath (Exelixis, likely Scribe) — fully
  automatable, no new adapter code needed once found; (2) genuinely new
  ATS platforms (Eightfold) — once found via the tool, add a detection
  signature to `detect_ats.py` and a new entry to `ats/REGISTRY`, same
  workflow already used to add Jobsyn.
- Playwright is a **new dependency**, not yet in `requirements.txt` or
  installed. It's already an open item twice on `ROADMAP.md` (Phase 1's
  JS-rendered fallback, Phase 4's Filler) — this ADR pulls it forward and
  gives it its first real use.
- **Status in the ADR is currently "Accepted"** — user was given the
  option to mark it "Proposed" instead if they want to sit with the
  decision before building anything; check which one is actually in the
  file if that matters for how committed the plan is.
- Explicitly deferred, not solved: fully custom sites with **no** JSON API
  at all (LLM-based DOM scraping was considered and rejected *for now* —
  revisit only once such a company is actually confirmed to exist).

### Known process issue to watch for (carried forward, unchanged)
Incremental patch tarballs were sent turn-by-turn across a long session
previously, and at least one failed to actually get extracted into the
user's local repo. Default to full-codebase tarballs over incremental
patches for anything nontrivial; if sending an incremental patch anyway,
tell the user explicitly to run `git status`/diff right after applying it.

### Explicitly NOT done yet (Phase 2, per ROADMAP.md — do not build early)
Unchanged: n8n webhook clients (scoring + resume assembly), cover-letter
LLM call, Critic blind-review step, weekly cloud token/cost log.

## How to pick this up

1. Read `docs/adr/0001-*.md`, `0002-*.md`, and **`0003-*.md`** if not
   already loaded.
2. Run `pytest tests/ -v` first to confirm state is still green (8 tests)
   — nothing should have changed here, but confirm before touching code.
3. **Two possible next threads, pick based on what the user wants:**
   - **(a) Registry completion:** user drives DevTools Network-tab
     checks for Exelixis and Scribe Therapeutics in their own browser,
     shares the request URL/headers/response shape found; AI maps it to
     an adapter and corrects/adds the `companies.yaml` entries. This is
     the same manual technique as Astellas, not blocked on any new code.
   - **(b) Build `discover_ats.py` per ADR-0003:** install Playwright,
     write the headless network-sniffing script, test it against
     Exelixis as the first real target (a good test case since it's
     JS-rendered-with-a-real-API-underneath, not the harder "no API at
     all" case). This is new feature work, follows the project's
     mentoring-mode/step-by-step working style like everything else.
4. Once registry is stable (all 10, or a clear subset) and Scout's been
   running cleanly for a few days, move to Phase 2 per `ROADMAP.md`.

---
*(End of handoff — paste everything above this line into a new chat.)*
