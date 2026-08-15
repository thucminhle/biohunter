# BioHunter — Scout & Ingestion: CustomAPI Dispatch Verified Against Real Source, AbbVie Geo-Filtered, Pacific Biolabs Fixed

**Session date:** 2026-08-15, third session of the day (continues from
`2026-08-15_2_BioHunter-CustomAPIDispatch-LivenessGate-Handoff.md`, which
built and logic-tested — but never live-tested — the `custom_api` Scout
dispatch and the Scribe Therapeutics liveness gate).

**Why this doc exists:** this session's job was mostly verification and
real-world testing of prior sessions' work, plus two new company-config
fixes that came out of that verification. Nothing here is a from-scratch
build; everything is either "confirmed real" or "found and fixed a real
gap the last session's assumptions had wrong."

---

## 1. Verified this session (real source, real network — not stand-ins)

- **`detector.py`'s `custom_api` dispatch branch — verified clean against
  real `custom_api.py`/`config.py`/`db.py`** (all three uploaded this
  session; `detector.py` itself was also uploaded and read in full).
  Every call site matches the real signatures exactly:
  `load_custom_api_config(company.name)` against
  `load_custom_api_config(company_name, path=...)`;
  `CustomAPIAdapter(config, limiter=limiter)` against
  `__init__(self, config, limiter=None)`; `adapter.fetch_postings(...)`
  against `fetch_postings(self, ats_slug)`. Exception behavior (uncaught
  `ValueError`/`requests.HTTPError`/`ConnectionError` falling through to
  `run_scout()`'s broad `except Exception`) also confirmed to match.
  **No mismatches found.** The one earlier-flagged gap (db.py apparently
  missing upsert/mark-stale functions) turned out to be a false alarm —
  those functions live in `detector.py` itself
  (`_upsert_postings`/`_mark_stale_postings`), not `db.py`; `db.py`
  really is just connection/schema, as uploaded.
  **Still not done:** no company has `ats_type: custom_api` in
  `companies.yaml` yet, so the branch has never actually fired against a
  real API. Interface-level verification is as far as this can go until
  a real `config/custom_apis.yaml` entry exists for some company.

- **Scribe Therapeutics liveness gate — confirmed live**, not just
  logic-tested. Ran `python -m biohunter.discover_ats` for real; the
  console output showed the gate firing exactly as designed:
  `[liveness-gate] rejected a fingerprint match confirmed dead:
  greenhouse/scribetherapeutics ... HTTP 404`, correctly falling through
  to `[manual]` instead of a false `[ok]`. Independently re-confirmed via
  direct fetch (not through the app) that **both**
  `job-boards.greenhouse.io/scribetherapeutics` (public board root) and
  `boards-api.greenhouse.io/v1/boards/scribetherapeutics/jobs` (the raw
  JSON API the site's own stale JS still calls) are genuinely dead —
  404 on both. Scribe has no working Greenhouse presence at all right
  now, at any level. `companies.yaml`'s comment for Scribe is updated to
  reflect this; `ats_type` correctly stays `null`.
  Also confirmed via that same real run: AbbVie and Pacific Biolabs both
  still report `[manual]` (no ATS fingerprint), and AbbVie's XHR capture
  showed no job-data endpoint — all consent/analytics/tracking noise.
  That's expected and separately explained below (AbbVie doesn't use one
  of the 6 known ATS platforms; it's an Attrax-branded in-house system).

## 2. Fixed this session — real company-config changes

- **`companies.yaml` — Pacific Biolabs.** Prior sessions' assumption
  ("plausible honest no-ATS-here result for a small CRO") was **wrong**,
  re-checked live this session. The page currently has **3 real, live
  postings**, plain server-rendered HTML (no Playwright needed), each
  linking straight to a Paylocity job page. Added
  `css_selector: "a[href*='paylocity.com']"`. Verified against real
  `scraper.py` source (uploaded this session): `extract_postings()`
  matches anchor elements directly (title = element text, url =
  `urljoin`'d href) — Paylocity's hrefs are already absolute, so this
  should work as written. **Not yet run through a real Scout pass** —
  next session should confirm it actually ingests 3 postings, or hits
  `detector.py`'s existing "css_selector matched zero listings" error
  path if the shape guess is wrong.

- **`companies.yaml` — AbbVie.** This took most of the session and went
  through several real dead ends worth knowing about so they don't get
  re-tried:
  - **Pagination (`javascript:pagination(N)`) needs a session cookie.**
    Confirmed via DevTools: it's a real `GET` to `.../en/jobs?page=2`
    with a `Cookie:` header attached — but a *stateless* fetch to that
    exact URL (no cookies) returns page 1's content unchanged. The
    server clearly keys pagination/search state off session state, not
    the URL alone. **Not built** — would need a `requests.Session()`
    that loads the base page first to acquire the cookie, then pages
    through with it. With 1,454 total results (~122 pages), this was
    also going to be a real scale decision (see below for why it's
    currently moot).
  - **Keyword search (`?q=scientist`) also needs session state,
    confirmed live.** Combining `q=scientist` with the (otherwise
    working) location-filter params caused the response to silently
    reset to the full unfiltered 1,454-result page. Same underlying
    issue as pagination. **Deliberately not chased further** — see next
    point for why.
  - **Location-radius search WORKS statelessly — confirmed live, this is
    what got built.** `https://careers.abbvie.com/en/jobs?q=&options=&page=1&ln=California%2C+USA&la=36.778261&lo=-119.4179324&lr=100&li=`
    (100km radius around California's centroid) returns the same 4
    real results via a cold, cookie-less fetch as it does in-browser.
    Set as AbbVie's new `careers_url`, with
    `css_selector: "a.attrax-vacancy-tile__title"` — confirmed against a
    real inspected DOM element (not guessed), and deliberately not a
    bare `href*='/en/job/'` match, since each job card also has two
    duplicate "Learn more" CTA links to the same URL that would
    otherwise create junk duplicate rows.
  - **As of this session, 0 of AbbVie's 4 current CA postings are
    Scientist roles** (Account Manager, 2x Sales Rep, District
    Manager) — a real, honest live result, not a bug. Only 4 results
    means no pagination is needed for this URL at all (well under the
    12/page default).
  - **The scientist-title narrowing is deliberately NOT solved on the
    AbbVie side.** Rather than build the session-cookie mechanism for
    one company's keyword search, the plan is to lean on
    `search_criteria.yaml`'s existing `title_include`, which is
    supposed to do this job downstream for every company already. See
    open item below — this wasn't confirmed before the session ended.

## 3. Open items — nothing chased further needs re-litigating, just picked up

- **`search_criteria.yaml` was never uploaded this session.** Need to
  confirm `title_include` actually contains "scientist" (or whatever the
  real target titles are) — otherwise AbbVie's 4 CA postings (and any
  future ones) will get ingested but filtered out downstream by a
  criteria file that doesn't know to look for them. This is the single
  most important thing to check first next session.
- Neither AbbVie's new geo-filtered `css_selector` config nor Pacific
  Biolabs' `css_selector` config has been run through a real Scout pass
  yet. Both are live-verified at the HTTP/HTML level, not yet at the
  full pipeline level (DB upsert, dashboard visibility, etc.).
- `custom_api` dispatch: still zero real companies configured to use it.
  Interface-level verification is complete; end-to-end is still open,
  same as last session.
- AbbVie pagination/keyword-search session-cookie mechanism: not built,
  deliberately deferred in favor of the geo-filter approach. Only worth
  revisiting if the geo-filter + title_include combination proves
  insufficient (e.g. a real target role posted outside CA's 100km
  radius that AbbVie's own filters would've caught but Scout's plain
  fetch won't).
- Same untouched list as before: guided onboarding wizard UI, Captain,
  Workspace, Writer/export.

## 4. Files to upload next session

**Must-have:**
- This handoff doc
- Current, real `config/companies.yaml` (this session's changes are
  final as of this handoff — Pacific Biolabs and AbbVie both edited,
  Scribe comment refreshed; nothing else touched)
- `config/search_criteria.yaml` — the one real unconfirmed dependency
  from this session, needed to close the loop on whether AbbVie's
  4 CA results will actually surface downstream

**If continuing custom_api real-world testing:**
- A real `config/custom_apis.yaml` entry for some company, if one gets
  hand-written before next session (still nothing here as of this
  handoff)

**If confirming Pacific Biolabs / AbbVie ingest correctly:**
- Just run a real Scout pass and report back what happened — console
  output plus whatever `companies.yaml`/DB changes resulted, same
  verification standard as everything else this session.

**Not needed:** anything Captain/Workspace/Writer-export specific, or
anything Astellas- or Scribe-specific (both closed).

## 4a. ADDENDUM — search_criteria.yaml checked, found a real structural gap

Uploaded and reviewed after this doc was first written; worth reading
this addendum before anything else next session.

- **`title_include` was empty** (no title filtering at all, for any
  company) — added `"scientist"` per explicit ask. This is global, not
  AbbVie-specific — worth confirming it's not too narrow for other
  companies already being tracked (e.g. a "Research Associate" role that
  doesn't literally contain "scientist").
- **`location_include` was Bay-Area-only** — added `"fresno"`,
  `"las vegas"`, `"santa barbara"` for AbbVie's specific current CA
  results, but this fix might not actually do anything — see next point.
- **Bigger finding: `scraper.py`'s real `extract_postings()` (confirmed
  against source, not guessed) only ever sets `RawPosting(title=title,
  url=href)` — `location` is NEVER populated for `css_selector`-scraped
  companies.** This affects both AbbVie and Pacific Biolabs, the two
  configs built this session. AbbVie's location info only exists inside
  its title text (e.g. "...Las Vegas, Nevada, Fresno, CA and Santa
  Barbara, CA"). **Whatever code actually applies `location_include`
  downstream was never uploaded this session** (almost certainly
  `scorer.py`, per the file tree) — so it's unknown whether a `None`
  location passes or fails that filter. That answer determines whether
  AbbVie/Pacific Biolabs postings survive at all, independent of what
  strings are in `search_criteria.yaml`.
  **Needed next session: `scorer.py`** (or wherever `location_include`
  actually gets checked), to confirm `None`-location handling before
  trusting that either company's postings will actually surface on the
  dashboard.

## 4b. ADDENDUM 2 — location filtering root cause found and stop-gap fixed
(`scorer.py` and `cli.py` both reviewed after 4a)

`scorer.py` itself has NO hard filter -- `location_include`/`location_exclude`
only get joined into prompt text there, as context for the LLM's holistic
judgment. That part of 4a's open question is resolved and was a red
herring. The REAL hard filter is one layer up, in `cli.py`'s
`keyword_filter_match()` -- shared by `cmd_list_postings`,
`cmd_score_postings` (as a pre-LLM-call filter, explicitly to avoid
wasting LLM calls on excluded rows), AND `dashboard.py` (confirmed via
the outline's own comment: dashboard reuses this exact function rather
than reimplementing it).

**Confirmed root cause:** `keyword_filter_match` lowercases `text or ""`
before checking `include` keywords. Since `scraper.py`'s
`extract_postings()` never populates `RawPosting.location` (title+url
only, confirmed against real source in section 2 above), EVERY
`css_selector`-scraped company's postings had `location = None` in the
DB, and a non-empty `location_include` (the Bay Area list has been
non-empty since before this session started) made `keyword_filter_match`
reject them unconditionally -- regardless of which strings were in the
list. **This means Pacific Biolabs' postings were already going to be
silently dropped by `score-postings`/`list-postings`/the dashboard,
independent of anything done to AbbVie today** -- not a new problem,
just a newly-discovered one.

**Fixed (stop-gap, explicitly not the real fix):** `keyword_filter_match`
in `cli.py` now skips the `include` check entirely when `text` is empty,
rather than auto-failing it. Chosen deliberately as the easiest fix for
now, not the right permanent one -- see the inline comment added at the
function itself for the full reasoning, and the next paragraph.

**Explicit product-direction note for future sessions:** the stated
longer-term goal is an industry- and location-agnostic app where users
add arbitrary companies and the app figures out how to import their
postings on its own. Under that goal, "no location data" becomes the
COMMON case, not a two-company edge case -- and silently letting
everything through a filter that can't actually check it stops being a
harmless stop-gap and starts being a real footgun once there are many
such companies. The real fix, deferred on purpose: give `css_selector`
configs (and any future auto-import mechanism) a way to actually extract
location text at scrape time, not just title+url. Worth designing this
alongside whatever "auto-figure-out-how-to-import" mechanism eventually
gets built, rather than patching it in again later as a second stop-gap.

**Not yet done:** neither this fix nor AbbVie's/Pacific Biolabs' configs
have been run through a real `score-postings` or dashboard pass together
-- next session should confirm all 7 postings (4 AbbVie + 3 Pacific
Biolabs) actually survive filtering end-to-end now, not just that the
function's logic looks right on inspection.

## 5. Working style — unchanged, worth restating given this session's pattern

This session leaned harder than prior ones on "guess, then verify live,
then correct" rather than getting things right on the first try —
worth normalizing rather than hiding: the `?page=2` guess was wrong
(returned page 1 unchanged), the AbbVie keyword-search guess was wrong
(silently reset to unfiltered results), and Pacific Biolabs' "no ATS
here" conclusion from two sessions ago was flat-out wrong. All three
were caught by actually re-checking against live responses instead of
trusting the prior claim or a first guess, which is the whole point of
this project's verification discipline. Continue treating every "should
work" as a hypothesis to check, not a conclusion — especially anything
inherited from an earlier handoff, including this one.

Files handed back complete and downloadable, never diffs. Rationale
explained before code. Every claim about what works is backed by either
a real run/fetch or an explicit "verified interface-level only, not
live" caveat.
