# BioHunter — Scout & Ingestion: discover_ats.py Built & Tested, CustomAPIAdapter Built

**Session date:** 2026-08-15 (continues from
`2026-08-14_2_BioHunter-SubsystemPlanning-ScoutHandoff.md`, which scoped
this session to Scout & ingestion only, priority order: `discover_ats.py`
→ `CustomAPIAdapter` + schema → guided wizard UI).

**Why this doc exists:** this session built and *live-tested*
`discover_ats.py` against 7 real companies (not just syntax-checked),
found and fixed two real bugs along the way, then built
`CustomAPIAdapter` + its config schema (logic-tested against mocked HTTP,
not a real company yet). The wizard UI is still untouched. This doc hands
over exactly what's confirmed working, what's confirmed broken/open, and
what each real company in this session's test batch actually needs next.

---

## 1. What was built and shipped this session

All four as complete downloadable files, never diffs, per the standing
workflow.

- **`src/biohunter/discover_ats.py`** (new) — headless-Playwright ATS
  discovery per ADR-0003. Reuses `detect_ats.py`'s `_PATTERNS` (imported,
  not duplicated). Default mode re-scans `companies.yaml` entries with
  `ats_type: null`; `--input` scans a fresh batch like `detect_ats.py`.
  Captures XHR/fetch response URLs during a real Playwright render and
  fingerprints against final URL + rendered HTML + those response URLs,
  catching JS-rendered career pages `detect_ats.py`'s plain
  `requests.get()` can't see. On no match, prints likely-JSON candidate
  endpoints as a head start for the (still unbuilt) wizard. Deliberately
  checks `robots.txt` before rendering (a divergence from `detect_ats.py`,
  named explicitly — a full headless render is heavier than one GET).
  Does NOT attempt scroll/click-triggered lazy loading — known,
  undecided-priority limitation, not hit yet in real testing.

- **`src/biohunter/detect_ats.py`** (updated) — fixed a real
  first-match-wins bug: when a company's page links to more than one
  board for the same ATS platform (e.g. a separate student/intern Workday
  tenant alongside the main one), it now deprioritizes matches containing
  `student`/`intern`/`campus`/`graduate` and prints every other candidate
  found, rather than silently picking whichever appeared first in the
  HTML. Confirmed fixing this exact case live (see Agilent, below).

- **`src/biohunter/scout/ratelimit.py`** (updated) — fixed a real bug in
  `allowed_by_robots()`: it was calling stdlib `RobotFileParser.read()`,
  which does its own internal fetch using Python's default urllib
  User-Agent (no way to pass it BioHunter's own `_USER_AGENT`), and
  stdlib `RobotFileParser` sets `disallow_all=True` on ANY 401/403
  response to *that* fetch — with zero relationship to what the file
  actually says. Confirmed against two real companies whose robots.txt,
  read directly, permits everything BioHunter was trying to fetch, but
  which were both getting blocked outright. Fixed by fetching
  `robots.txt` with `requests` + the real `_USER_AGENT` first, then
  handing the text to `rp.parse()` (no network I/O), preserving the same
  fail-open philosophy for genuine fetch failures. **Not yet fixed:**
  `_USER_AGENT`'s placeholder `contact: set-your-email-here` — small,
  your call when to swap in a real address.

- **`src/biohunter/ats/custom_api.py`** (new) — `CustomAPIAdapter` class
  + `CustomAPIConfig`/`FieldMap`/`PaginationConfig` schema +
  `load_custom_api_config()` loader, per the ROADMAP's "mapping is data,
  not generated code" design. Dot-path field resolution, GET/POST,
  page-number pagination with a hard safety cap, `url` or
  `url_template`-with-`{raw.path}`-placeholders for constructing a URL
  from an id. Fails loudly (`ValueError`, not silent fallback) on a
  mapping that doesn't resolve against real data. **Logic-tested** with 8
  passing tests against mocked HTTP responses (path resolution,
  pagination-stops-on-empty-page, both validation-error cases, bad-field
  error case) — genuinely exercised, not just syntax-checked, but never
  run against a real company's real API. **Architectural note:** NOT
  added to `ats/__init__.py`'s `REGISTRY` — it can't be a stateless
  singleton like the six platform adapters, since every company's
  URL/fields/pagination differ completely, not just a slug. Needs a
  config bound per-company at construction time instead.

---

## 2. Real companies tested this session — status per company

Tested via `detect_ats.py` then `discover_ats.py` in sequence, across two
batches (an initial 3-company test batch, then a user-requested 5-company
batch: Agilent, AbbVie, Tempus AI, Addition Therapeutics, Pacific
Biolabs). Results, and what each one still needs:

| Company | Status | Next step |
|---|---|---|
| **Agilent** | ✅ Correct — `workday`, `agilent.wd5/Agilent_Careers` | None. The multi-match fix (see above) resolved this live; the other candidate (`Agilent_Student_Careers`) is now correctly reported as passed-over, not silently picked. |
| **Tempus AI** | ✅ Correct — `workday`, `tempus.wd5/Tempus_Careers` | None (direct Workday URL was given as input). |
| **Scribe Therapeutics** | ❌ **`companies.yaml` currently has a WRONG entry** — `discover_ats.py` matched its old, now-**dead** Greenhouse board (`job-boards.greenhouse.io/scribetherapeutics`, confirmed by the user to 404) because a stale link/reference to that URL still appears somewhere on `scribetx.com/careers`'s rendered page. Fingerprint matching only ever checks "does a URL matching this shape appear," never "is it alive." | **Real, still-open bug in `discover_ats.py`**: needs a liveness-gate (construct the real posting-list URL for a match and confirm it responds before declaring `[ok]`) — `scraper.py` already has a working `_check_greenhouse_url_alive()` from the dead-link-checker work that could back this. Not built this session. Until fixed, manually correct or remove Scribe's `companies.yaml` entry — its real board doesn't currently exist (confirmed: `scribetx.com/careers` has no job postings at all right now). |
| **AbbVie** | ⚠️ Real finding, not a bug: platform is **Attrax** (a career-site CMS, confirmed via its CDN URL in a fetched page — not one of the six known platforms). Job data is **server-side rendered directly into static HTML** (confirmed: fetched `careers.abbvie.com/en/jobs` and saw real postings — titles, locations, job IDs like `R00148928` — with zero JS execution). This means AbbVie is a **CSS-selector fallback-scrape candidate, not a `CustomAPIAdapter` candidate** — there's no JSON API being called on page load, which is exactly why `discover_ats.py`'s XHR/fetch capture only found cookie-consent/reCAPTCHA noise (12 endpoints, none job-related). Robots.txt no longer blocks it (fixed this session) — this is the real, honest result underneath the old false block. | Needs a `css_selector` config for the wizard's CSS-selector path (not yet built). Real, confirmed permalink shape: `/en/job/{slug}-jid-{number}`. Pagination on the listing page goes through `javascript:pagination(N)` — not yet investigated how that's actually fetched. |
| **Addition Therapeutics** | ⚠️ Real, confirmed-live Greenhouse board exists (`job-boards.greenhouse.io/additiontherapeutics` — verified via search, real current postings like "Director, Liver Therapeutic Applications"), but neither `detect_ats.py` nor `discover_ats.py` can find it automatically, because `additiontx.com`'s **homepage doesn't link to it at all** (confirmed: only cookie-consent/accessibility-widget noise in the candidate endpoints, and the real board URL never appears in rendered HTML either). This is a real, un-addressed limitation shared by both tools: neither follows a "Careers" nav link if given a homepage instead of the actual careers page. | **Hand-set directly** — no more automation needed, we already have ground truth: `ats_type: greenhouse`, `ats_slug: additiontherapeutics`. |
| **Pacific Biolabs** | ⚠️ Mixed: `detect_ats.py`'s plain `requests.get()` gets a genuine `403 Forbidden` (bot-protection on the real page, confirmed separate from the robots.txt bug, unfixed — deliberately NOT fixed by spoofing more convincing headers, since that crosses from polite identification into active evasion; flagged as a boundary, not silently crossed). `discover_ats.py`'s headless render got PAST that block (real evidence Playwright's browser fingerprint reads as more legitimate than a bare `requests` call) but found **zero** ATS fingerprint and **zero** candidate endpoints. | Needs you to check whether `pacificbiolabs.com/about/career-opportunities-2/` even has current postings right now — plausible this is just an honest "no live job board system here" result for a small CRO, not a bug. If there are postings, it's a `css_selector` candidate too. |

**Note:** this session never got the post-run `companies.yaml` re-uploaded, so the table above reflects what *should* be true based on each run's printed output — worth uploading the real current file next session rather than trusting this reconstruction.

---

## 3. Astellas — a loose thread from a prior session, partially advanced

Not part of this session's 5-company batch, but came up because
`discover_ats.py`'s first test run (against Scribe + Astellas) found
Astellas' real search API for the first time:
`https://prod-search-api.jobsyn.org/api/v1/solr/search?page=1&num_items=10`.
This resolves the "real search API isn't reachable via available tools"
blocker from the 2026-08-11/12 session.

**Not yet done:** the actual response body was never fetched/inspected
this session, so `custom_api.py`'s docstring includes only a clearly-
labeled **placeholder** example config for Astellas — field names in it
(`job_title`, `job_id`, etc.) are illustrative guesses, not confirmed
real keys. Fetching that URL for real and inspecting its actual JSON
shape is the natural next concrete step if Astellas is prioritized next.

---

## 4. What's NOT in scope / not touched this session

Per the 2026-08-14 handoff's explicit instruction (small, self-contained
sessions, one subsystem at a time): Captain, Workspace, and Writer/export
were not touched. Within Scout & ingestion itself, still not started:

- Guided onboarding wizard UI (both the JSON-API path and the
  CSS-selector path) — genuinely untouched, not even scaffolded.
- Wiring `custom_api` as a real `ats_type` into Scout's per-company
  dispatch loop (`if ats_type == "custom_api": build CustomAPIAdapter
  from config`) — **blocked on `scout/__init__.py`**, which has not been
  uploaded in any session so far despite being listed as needed.
- Browser extension capture — lowest priority per the roadmap, not
  started.
- The Scribe Therapeutics liveness-gate fix for `discover_ats.py`
  (Section 2, above) — real, scoped, small, not built.
- `discover_ats.py`'s scroll/click-triggered lazy-loading gap — known
  limitation, not hit in real testing yet, undecided priority.

---

## 5. Files to upload next session

**Must-have:**
- This handoff doc
- `docs/ROADMAP.md` (unchanged this session, but next session should
  confirm it's still current)
- Current, real `config/companies.yaml` (post this session's Agilent fix,
  Tempus addition, and whatever manual corrections you make for Scribe/
  Addition Therapeutics per Section 2 above — this session's copy is
  stale)

**If continuing Scout & ingestion dispatch wiring:**
- `src/biohunter/scout/__init__.py` — genuinely blocking, requested
  across multiple sessions now, still not uploaded

**If continuing Astellas or AbbVie specifically:**
- Nothing extra needed from you except running the fetch/DevTools check
  yourself and reporting back what the real response/page structure
  looks like — I can pick up from there.

**Not needed:** anything Captain/Workspace/Writer-export specific, same
exclusion list as the prior handoff.

---

## 6. Working style — unchanged

Vibe-coded: files handed back complete and downloadable, never diffs or
snippets. Rationale explained before code. Existing logic
extended, not duplicated, wherever practical (this session:
`discover_ats.py` imports `detect_ats.py`'s patterns rather than
re-declaring them; `custom_api.py` reuses `ATSAdapter`/`RawPosting` from
`base.py` and `RateLimiter` from `ratelimit.py`). Every claim about what
works is backed by either a real run (discover_ats.py, detect_ats.py,
ratelimit.py — all live-tested against real companies/sites this
session) or an explicit "logic-tested against mocks, not live" caveat
(custom_api.py) — never presented as more verified than it actually is.
