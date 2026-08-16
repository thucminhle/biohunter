# BioHunter — Scout & Scoring: Description Backfill Built and Confirmed Live, AbbVie's 4 Postings Fully Scored

**Session date:** 2026-08-15, fourth session of the day (continues from
`2026-08-15_3_BioHunter-CustomAPIVerified-AbbVieGeoFilter-PacificBiolabsFix-Handoff.md`,
which built AbbVie's geo-filtered `css_selector` config and Pacific
Biolabs' selector but never ran either through a real Scout pass, and
found -- but didn't fully resolve -- a mismatch between that session's
handoff addenda and the actual uploaded `search_criteria.yaml`).

**Why this doc exists:** this session closed the loop that `_3` left
open -- ran `score-postings` and `run-scout` for real, found a real
structural gap (`css_selector` companies never get a job description at
all), designed and built the fix, verified it against real DOM
inspection and reconstructed-but-real HTML, and then got real
confirmation from an actual `run-scout` + `score-postings` pass that it
works. Nothing here is guessed; anywhere this doc says "confirmed," it's
because either a real console output was pasted in, or code was actually
executed against real or hand-confirmed-real data during the session.

---

## 1. Verified this session (real execution, real console output, real DOM)

- **`search_criteria.yaml`'s `title_include` addendum was confirmed, via
  actually running `config.py`'s real `load_search_criteria()`, to still
  be empty** (`[]`), not `["scientist"]` as `_3`'s addendum 4a claimed.
  Same for `location_include` missing `fresno`/`las vegas`/
  `santa barbara`. **Resolved this session, explicitly: title_include
  stays empty going forward** -- this was a deliberate call, not an
  unresolved bug. No further yaml edit needed here.
- **`keyword_filter_match()` -- copied verbatim from the real `cli.py`
  and actually executed** (not hand-traced) against AbbVie's 4 and
  Pacific Biolabs' 3 real titles (live-fetched this session) plus the
  real loaded criteria. All 7 passed. Confirmed structurally: title
  passes because `title_include` is empty (no restriction), location
  passes because `location` is `None` for every `css_selector`-scraped
  posting, which trips the existing stop-gap's empty-text skip.
- **`extract_postings()` -- actually executed** against reconstructed
  HTML built from real live-fetched titles/hrefs/selectors: correctly
  extracts AbbVie's 4 (and correctly skips the duplicate "Learn more" CTA
  anchor) and Pacific Biolabs' 3, `location` genuinely `None` on every
  one -- confirms `_3`'s claim about `scraper.py`'s shape, now by
  execution, not just reading.
- **A real `run-scout` pass, pasted in full:** `AbbVie (scrape): 4 new /
  4 total` -- exact match to the code-level extraction count above.
  `[ERROR] Pacific Biolabs: 403 Client Error: Forbidden` -- a **new,
  distinct failure** from the robots.txt-fetch-under-generic-UA bug `_3`
  already fixed in `ratelimit.py`. This is the actual page `GET` itself
  getting blocked even with the real `_USER_AGENT` header, i.e.
  bot/WAF-level blocking of `requests`-style traffic, not a robots.txt
  parsing issue. Re-fetched the same URL live afterward (still fully
  live, same 3 postings) to confirm it's not a site outage. `[ERROR]
  Scribe Therapeutics: No ats_type and no css_selector configured` --
  **expected, by design**, matches `_3`'s deliberate decision to leave
  Scribe manual. Not a regression.
- **Checked `detector.py`'s real Scout dispatch and confirmed
  `CompanyConfig.renderer` (`None | "playwright"`) is never read
  anywhere in it, and `scraper.py` has no Playwright code at all** -- the
  field exists in `config.py` but is fully unwired. Setting
  `renderer: playwright` on Pacific Biolabs right now would do nothing;
  a real browser-rendered fetch path doesn't exist in this codebase yet.
- **A real `score-postings` run on AbbVie's 4 (before this session's
  fix):** `Scored 0, skipped 4, of 4 filtered posting(s)`. Filter passed
  4/4 as predicted; all 4 skipped for `no job description stored`.
  Root-caused to `extract_postings()` never setting `description` at
  all -- confirmed by reading real source AND by this real skip output
  matching exactly.
- **DOM-inspected live, in two rounds, by the user directly against a
  real AbbVie detail page**
  (`.../district-manager-dermatology-.../jid-29123`): confirmed
  `div[aria-label='Job description']` is a real, unique
  (`querySelectorAll(...).length === 1`) container that sits *before*
  its sibling `<script type="application/ld+json">` at the outer
  wrapper level (not nested inside it) and outside the
  `vacancy-buttons-widget`/`social-share-widget` siblings -- so it
  naturally excludes JSON-LD garbage and the Apply/Save/share UI without
  any extra filtering logic needed.
- **After the fix shipped, a real `run-scout` pass, pasted in full:**
  `15 companies checked, 0 new posting(s), 2 error(s)`. Zero new
  postings is correct (AbbVie's 4 were already `'new'`-status from the
  prior run; this pass only needed to backfill `description`, not
  insert rows). The 2 errors are the same two already-open, already-
  understood ones (Pacific Biolabs 403, Scribe no-selector) -- nothing
  new broke. **User confirmed directly: all 4 AbbVie postings now have
  real job descriptions.**
- **A real `score-postings` run after that: all 4 AbbVie postings
  received scores.** Dashboard screenshot confirms `status: scored` on
  all 4, with fit scores of 1-2/10 across the board (District Manager
  1/10, Specialty Rep x2 at 1/10 and 2/10, Strategic Account Manager
  1/10). These are honest, low, expected scores -- sales/account-manager
  roles genuinely don't fit a scientist-background candidate; this is
  the filter and scorer both working correctly, not a bug. **Not yet
  independently spot-checked that the underlying description text being
  scored against is clean/complete** (see open items) -- the scores
  themselves look sane given the titles, which is a good sign but not
  the same as reading the actual stored description column.

## 2. Built this session — real code, written and exercised against real-confirmed data

Root cause: `scraper.py`'s `extract_postings()` (used by every
`css_selector` company) only ever sets `title`+`url` on `RawPosting` --
it scrapes the *listing* page only and never visits each job's own page.
Unlike the six real ATS adapters (each of which hits a per-job detail
endpoint for description), the fallback scrape path had no equivalent
second request at all.

- **`scraper.py` -- new `fetch_job_description(url, css_selector,
  limiter) -> str | None`.** Reuses `fetch_page()`'s same
  robots-check + rate-limit + real `_USER_AGENT` request path (this is a
  second real request to the same company domain `fetch_page()` already
  hit, so it must go through the same politeness gate). Returns the
  matched element's **raw inner HTML** (`el.decode_contents()`), not
  parsed text -- so it flows through `detector.py`'s existing
  `_clean_description()` instead of a second, parallel cleanup routine.
  Returns `None` on any failure (robots disallow, request error,
  selector-miss) and logs a `WARNING` in each case, tagged `[scrape]` --
  same established pattern as the real `[jobvite]`/`[workday]` WARNING
  lines already seen in this session's own `run-scout` output. One job's
  description failing never aborts the rest of the company's run.
- **`detector.py` -- new `_backfill_missing_descriptions(conn, company,
  company_id, limiter)`.** Queries `WHERE company_id = ? AND description
  IS NULL`, fetches each exactly once, updates in place via
  `_clean_description()`. Wired into `run_scout()`'s `css_selector`
  branch, called **unconditionally** -- explicitly NOT gated on the
  listing page's `changed`/content-hash check, since a posting can have
  `description IS NULL` on a run where the listing itself is
  byte-identical to last time (first-seen before this feature existed,
  or a prior fetch attempt failed). Gating on `changed` would have
  silently skipped exactly the postings this exists to catch. No-op for
  any company without `description_css_selector` set -- fully additive,
  zero behavior change for existing configs that don't use it.
- **FETCH-ONCE, NOT EVERY RUN -- confirmed as the user's explicit,
  deliberate choice this session.** Only rows where `description IS
  NULL` are touched; a posting that already has a description is never
  re-fetched. Chosen specifically because a real second request per
  posting per run is exactly the kind of traffic that already tripped
  Pacific Biolabs' 403 this same session. **Known, accepted
  consequence, not hidden:** if a company edits a live posting's text
  after first successful fetch, that edit will NOT be pulled in under
  this scheme. Worth remembering months from now if a stored description
  ever looks stale against the live page.
- **`config.py` -- `CompanyConfig.description_css_selector: str | None
  = None`**, parsed in `load_companies()`. Fully additive.
- **`companies.yaml` -- AbbVie's entry updated** with
  `description_css_selector: "div[aria-label='Job description']"`,
  comment recording the real DevTools confirmation (unique match,
  sibling-not-nested JSON-LD/vacancy-buttons exclusion) and the
  fetch-once trade-off inline.
- **Verified before handoff, not just written:** fed HTML matching the
  exact real confirmed nesting from the user's two DevTools screenshots
  through the real selector logic -- confirmed the JSON-LD blob and
  Apply/Save button text never appear in the extracted content. Then ran
  the real `_clean_description()` (copied verbatim from `detector.py`)
  against that extracted HTML and got a clean, readable final
  description (Company Description → About AbbVie → Job Description →
  bullets → Qualifications), matching the real page's actual visible
  structure confirmed via live fetch several turns earlier. This was
  reconstructed-HTML verification at the time; **the subsequent real
  `run-scout` + `score-postings` pass is what actually confirmed it
  live**, per the section above.

## 3. Open items

- **Pacific Biolabs 403 -- parked, per explicit user instruction this
  session.** Real bot/WAF-level blocking of `requests`-style traffic,
  confirmed distinct from the earlier (already-fixed) robots.txt/UA bug.
  No working renderer fallback exists in this codebase --
  `CompanyConfig.renderer` is present but confirmed unwired in
  `detector.py`; a real Playwright (or similar) fetch path would be new
  build work, not a config change. Once/if this gets unblocked, Pacific
  Biolabs will need its own `description_css_selector` built fresh --
  nothing from AbbVie's selector transfers (different site, different
  platform: Attrax vs. whatever Pacific Biolabs' WordPress-adjacent site
  uses).
- **Fetch-once known consequence** (AbbVie posting edits after first
  fetch won't be re-pulled) -- not a bug, just flagged so it isn't
  mistaken for one later.
- **Not yet done: independently reading the actual stored `description`
  column for AbbVie's 4 postings**, as opposed to inferring it's clean
  from the scores looking sane. Low scores on sales-y titles are
  expected either way, so this isn't strong confirmation that the
  description text itself is complete/unmangled. Cheap to check next
  session if it becomes relevant (e.g. before ever running Writer
  against one of these).
- **Writer/Critic pipeline has not been touched or tested against any of
  these 4 AbbVie postings this session** -- scoring only. Whether a
  `css_selector`-sourced, backfilled description works cleanly as
  Writer's input is unconfirmed and out of this session's scope.
- Same untouched list as `_3`: guided onboarding wizard UI, Captain,
  Workspace, Writer/export -- still nothing done here.

## 4. Files to upload next session

**If continuing Scout/scoring work:**
- This handoff
- Current `config/companies.yaml` (this session's AbbVie
  `description_css_selector` addition is final as of this handoff)
- If picking up Pacific Biolabs' 403: nothing new needed yet, it's still
  at the "parked, not investigated" stage from this session

**Note: next session's stated focus is different** -- the user wants to
work on **browser extension capture** next, which doesn't appear
anywhere in `FILE_TREE.txt` from this session (no browser-extension
directory exists in the tree as uploaded) and wasn't discussed in any
handoff read so far. This is either a genuinely new subsystem or
something documented in `docs/ROADMAP.md`/`docs/design/
biotech-job-hunter-design.md` (neither uploaded this session, both
listed in `FILE_TREE.txt`). **Next session should start by uploading
whichever of those actually covers it**, rather than guessing what
"browser extension capture" refers to architecturally.

## 5. Working style — unchanged, same discipline this session followed

Every claim in this doc is backed by either a real pasted console
output, a real DOM inspection the user did directly, or code actually
executed this session against real or hand-confirmed-real data -- same
standard `_3` set. Where something was only verified against
reconstructed (not literally live-fetched) HTML, that's stated
explicitly above rather than blurred into "confirmed." Files handed back
complete and downloadable, never diffs. Continue treating every "should
work" as a hypothesis to check, not a conclusion -- this session's own
`title_include` mismatch (claimed fixed in `_3`'s addendum, actually
still empty when re-checked) is itself a good example of why.
