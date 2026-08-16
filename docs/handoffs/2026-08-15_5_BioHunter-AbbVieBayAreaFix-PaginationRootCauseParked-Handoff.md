# BioHunter — Scout: AbbVie Re-Centered on the Real Bay Area, Pagination Root Cause Diagnosed and Parked

**Session date:** 2026-08-15, fifth session of the day (continues from
`2026-08-15_4_BioHunter-DescriptionBackfill-ScorePostingsConfirmedLive-Handoff.md`,
which built and confirmed live the `css_selector` description-backfill
feature for AbbVie's original 4 Fresno-area postings).

**Why this doc exists:** the user found a real AbbVie Scientist II
posting via LinkedIn that Scout had never surfaced. That turned into a
real root-cause investigation (not a filter bug -- a mis-centered search
radius), a real fix (a corrected `careers_url` obtained through AbbVie's
own site search, same discipline as every prior URL in this config), and
then a related but separate discovery (page=2 pagination silently fails
statelessly) that's being deliberately parked this session rather than
built.

---

## 1. Verified this session (real distance math, real live fetches, real user-provided URLs)

- **Root cause of the missing Scientist II posting, confirmed by real
  calculation, not guessed:** AbbVie's `careers_url` at the start of this
  session used `la=36.778261, lo=-119.4179324` -- Google's generic
  geographic centroid for "California, USA," which sits in the Central
  Valley near Fresno. Haversine distance from that point to South San
  Francisco: **282.1 km**, 182km outside the configured `lr=100` radius.
  This is why Scout's 4 results were all Fresno/Central-Valley sales
  roles and never included the real South San Francisco Scientist II
  posting (`jid-31676`) the user found via LinkedIn -- not a
  `title_include`/`location_include` filtering bug (both were already
  confirmed working correctly in prior sessions), a geographically
  mis-centered search.
- **Naive fix attempted and confirmed NOT to work statelessly:**
  hand-editing `la`/`lo`/`ln` to San Francisco coordinates, live-tested
  twice. First attempt silently reverted to the *original* Fresno-area 4
  results (response's own destination-url metadata showed AbbVie's
  server had substituted back the old params). Second attempt (different
  coordinates + cache-buster, to rule out simple caching) reset to the
  full 1,465 unfiltered results instead. Confirmed this is the same
  session-cookie dependency `_3`'s handoff already found for pagination
  and keyword search, now shown to also affect location-search changes
  made by hand rather than through the site's own search flow.
- **Real fix obtained by the user directly through AbbVie's own site
  search UI** (same method used to find the original, now-corrected
  URL) -- `ln=San Francisco Bay Area, CA, USA` with real matching
  `la=37.8271784, lo=-122.2913078`. Confirmed live via a cookie-less
  fetch matching the user's exact requested params (destination-url
  metadata matched what was requested, unlike the hand-edited attempts):
  **51 real results, Scientist II (`jid-31676`) confirmed present.**
- **`size=48` confirmed as a real ceiling, live:** `size=100` on this
  same URL silently falls back to the full 1,465 unfiltered results.
  `48` matches the site's own "Results per page" UI options (12/24/48)
  and is the largest value that returns real filtered results.
- **Pagination root cause explained precisely, via the user's own two
  real URLs (`page=1` and `page=2`, otherwise identical):** live-tested
  `page=2` on the corrected Bay Area URL -- it ALSO resets to the full
  1,465 unfiltered results, exactly like `page=1`'s earlier hand-edited
  failures. Mechanism, explained to the user this session: visiting
  `page=1` in a real browser has the server set a session cookie that
  associates that specific `ln`/`la`/`lo`/`lr` search with the session;
  the browser auto-attaches that cookie on the `page=2` click, so the
  server knows what's being paginated. A stateless `requests.get()` (or
  this session's `web_fetch` calls) sends no cookie at all -- each
  request looks like a brand-new visitor with no established search
  context, so `page=2` has nothing to page through and falls back to
  the unfiltered default. Same root mechanism already suspected for
  keyword search in `_3`, now confirmed directly for pagination too.
- **Company census taken, real, by actually parsing the real
  `companies.yaml`:** only **AbbVie and Pacific Biolabs** use the
  `css_selector` fallback-scrape path. The other 12 configured companies
  all go through real ATS adapters (7x `workday`, 2x `greenhouse`, 1x
  each `jobsyn`/`jobvite`/`lever`) -- none of which have this pagination
  problem, since each ATS API returns its full result set (including
  descriptions) in one structured call. Scribe Therapeutics remains
  deliberately unconfigured. This means the pagination gap currently
  affects at most 2 companies, and Pacific Biolabs' page 1 itself is
  still separately blocked by its own 403 (open item, unrelated), so
  building real pagination support would only concretely help AbbVie
  today.

## 2. Fixed this session — real companies.yaml edit

- **`companies.yaml` -- AbbVie's `careers_url` corrected** from the
  Fresno-centroid URL to the real, user-obtained Bay Area URL
  (`page=1&size=48&ln=San+Francisco+Bay+Area...`). `css_selector` and
  `description_css_selector` left unchanged -- both already confirmed
  working against this same site/template in `_4`, this was purely a
  URL swap, no code changes needed.
  - Comment block rewritten (not just appended-to) to remove now-stale
    claims from `_3` (e.g. "only 4 results, no pagination needed" no
    longer true at 51 results) while preserving the real history and
    reasoning that's still accurate (why keyword search was rejected,
    why the css_selector avoids the duplicate "Learn more" CTA, why
    `title_include` being empty means no title narrowing currently
    happens for AbbVie at all).
  - **KNOWN, ACCEPTED LIMITATION recorded inline:** 51 real results
    exist; `size=48` page 1 only carries 48 of them. The remaining 3
    are unreachable without solving the session-cookie pagination
    problem below. Accepted for now specifically because Scientist II
    (the posting that surfaced this whole investigation) is confirmed
    inside the 48 -- revisit if a real posting is ever confirmed missing
    specifically because it landed on page 2.

## 3. NOT done this session -- explicitly parked, per direct user instruction

- **Real pagination support for `css_selector` companies (a
  `requests.Session()`-based fetch, cookie-jar persisted across
  `page=1`, `page=2`, ... calls) was scoped in conversation but
  deliberately NOT built.** User's own words: "have this issue be
  parked for now." Scoped shape, for whenever it's picked back up:
  - New function, likely `fetch_paginated_pages()` in `scraper.py` --
    uses a real `requests.Session()` (not the one-off `requests.get()`
    `fetch_page()`/`fetch_job_description()` currently use), fetches
    `page=1` first to establish the session cookie, then `page=2`,
    `page=3`, ... through the SAME session object, stopping when a page
    returns zero new listings (or hits some sane max-pages guard).
  - Needs real `requests.Session()` testing, which cannot be done via
    this environment's `web_fetch` tool (no persistent cookie jar across
    calls) -- genuinely requires the user's own Python environment to
    verify, same category of limitation as the original pagination/
    keyword-search discovery in `_3`.
  - Reusable, not AbbVie-specific in principle -- but currently only
    concretely useful for AbbVie, since Pacific Biolabs (the only other
    `css_selector` company) is still blocked earlier in the pipeline by
    its own unrelated 403.

## 4. Open items, updated

- **Pacific Biolabs 403** -- unchanged, still parked from `_4`.
- **AbbVie pagination (session-cookie-based, `requests.Session()` fix
  scoped above)** -- NEW this session, explicitly parked per direct
  instruction. Missing 3 of AbbVie's 51 real Bay Area postings until
  built.
- **Not yet run live this session:** the corrected AbbVie `careers_url`
  has NOT yet been run through a real `run-scout` + `score-postings`
  pass. Everything in section 1 is confirmed via direct `web_fetch`
  calls and the user's own browser-obtained URLs, not yet via the
  actual production pipeline. Real next step: run `run-scout` with the
  corrected `companies.yaml`, confirm ~48 new/changed AbbVie postings
  land (old 4 Fresno-area ones should be marked stale, correctly, since
  they're outside this new search), then `score-postings`, then
  specifically check the dashboard for the Scientist II card -- same
  "confirm live, don't assume the code trace is enough" discipline
  `_4`'s AbbVie-description fix already followed successfully.
- Fetch-once-only description backfill's known consequence (from `_4`)
  -- still unchanged, still just a reminder, not a bug.
- Same untouched list as prior sessions: guided onboarding wizard UI,
  Captain, Workspace, Writer/export.
- **Browser extension capture** -- still the user's stated next topic
  after Scout/scoring work wraps; still nothing uploaded that documents
  it (`docs/ROADMAP.md` / `docs/design/biotech-job-hunter-design.md`
  were requested but not yet provided as of this handoff).

## 5. Files to upload next session

**Must-have, if continuing AbbVie verification:**
- This handoff
- Current `config/companies.yaml` (this session's AbbVie `careers_url`
  correction is final as of this handoff)
- The real `run-scout` and `score-postings` console output once run --
  this is the one real unconfirmed step left from this session

**If picking up AbbVie pagination (currently parked):**
- Nothing new needed yet; scoped but not started

**If switching to browser extension capture as previously requested:**
- `docs/ROADMAP.md` and/or `docs/design/biotech-job-hunter-design.md` --
  whichever actually documents this subsystem, since it doesn't appear
  in `FILE_TREE.txt`'s existing directory structure and hasn't been
  described in any handoff read so far

## 6. Working style -- unchanged

Every claim above is backed by either a real distance calculation, a
real live fetch (including two the user obtained directly through
AbbVie's own site UI, not hand-edited), or a real parse of the actual
`companies.yaml`. Where something is scoped but not built (pagination),
that's stated plainly as parked, not implied to be done. Files handed
back complete, never diffs. Same discipline as every prior session this
day: treat "should work" as a hypothesis, verify live before trusting
it -- this session's own two failed hand-edit attempts at a Bay Area URL
before the user supplied a real one are a good example of why.
