# BioHunter — Browser Extension Capture Built, Live-Tested; LLM-Assisted Multi-Site Extraction Scoped, Not Built

**Session date:** 2026-08-16/17, continues from `2026-08-15_5_BioHunter-AbbVieBayAreaFix-PaginationRootCauseParked-Handoff.md` (AbbVie work is fully closed out and confirmed live as of that handoff -- 52 real Bay Area postings, scored -- do not re-verify or re-litigate it).

**Why this doc exists:** the user picked up ROADMAP.md's "Browser extension capture" item -- click-to-save a LinkedIn job posting into the dashboard, since a large share of biotech roles are never on job boards Scout monitors directly. This session built it, iterated through three real usability problems the user hit live, and fixed each one. The extraction itself (LinkedIn DOM selectors) remains **unverified against a real live page** -- flagged explicitly below, not glossed over.

---

## 1. Built and confirmed live this session

- **New JSON route, `POST /api/postings/capture`** in `dashboard.py` -- accepts `{company, title, url, location?, apply_url?, description}`, returns `{status: "created"|"duplicate", posting_id, dashboard_url}`. Shares its insert/dedup logic with the existing HTML form route (`posting_manual_create`) via a new factored-out `_create_manual_posting()`, so the two entry points can't silently drift apart. **User confirmed live**: a real capture landed in the dashboard, rendered correctly on the posting-detail page.
- **`postings.apply_url` column, added via `migrate_add_apply_url.py`** (a new standalone migration script, following this project's existing `migrate_repost_tracking.py` pattern -- written against a plain `sqlite3` connection since `db.py` wasn't uploaded this session, so its `get_connection()` signature isn't confirmed). Stores the *direct application link* for a posting -- e.g. LinkedIn's "apply on company site" link -- distinct from `postings.url` (the LinkedIn source link, used for dedup) and distinct from `companies.careers_url` (the company's general careers page, used by Scout). **User confirmed live via screenshot**: a real Merck posting shows both "original posting" and a bold "apply here" link on the detail page, correctly pointing at the direct-apply URL.
  - **Known gap, accepted as-is:** postings captured *before* this migration have `apply_url = NULL` and will only show "original posting" -- not retroactive, not a bug.
- **`_distinct_companies()` fixed** to inner-join `postings`, so a company with zero postings (e.g. one created by a since-deleted test capture) disappears from the dashboard's company-filter dropdown on its own -- no delete-company UI needed, self-maintaining by design (user's own framing: "if there is NO job posting for that company then it should just disappear from the company drop down list").
- **Manifest V3 browser extension**, targets Brave and Coc Coc (both Chromium-based -- one build covers both, confirmed no separate manifest needed). Files: `manifest.json`, `background.js`, `capture.html`/`capture.js`, `linkedin_extract.js`, `options.html`/`options.js`.
  - **Popup-window redesign (real fix for a real bug the user hit):** originally used Manifest V3's default `action.default_popup`, which closes the instant it loses focus -- meaning clicking over to the LinkedIn page to select/copy text for pasting wiped out whatever was already typed. Fixed by switching to `chrome.windows.create()` opening a standalone window (`capture.html`) instead, which survives that focus loss. **User confirmed live**: copy/paste into the capture window now works without erasing prior input.
  - **Draft autosave**, on top of the window fix: every field change is debounced-saved to `chrome.storage.session`, keyed by tab ID, and restored on reopen -- a second layer of protection if the window gets closed by hand mid-fill. Confirmed live by the user (close without submitting, reopen, draft was still there).
  - **Generic fallback for non-LinkedIn pages**: no site-specific adapter -- pre-fills title/URL from the tab itself, leaves company/description for manual entry. Not yet exercised live by the user this session (LinkedIn was the only site tested).

## 2. Explicitly unverified -- flag for the next session, don't assume it's correct

- **`linkedin_extract.js`'s CSS selectors were never checked against a real live LinkedIn DOM in DevTools.** They're best-guess, written from general knowledge of LinkedIn's job-page structure, same caveat repeated in three places in the code (file header, module comment, this handoff). The user has NOT reported whether title/company/location/description auto-fill correctly or come back empty/wrong on a real posting -- only that the capture mechanism itself (popup, paste, submit, apply_url) works end to end using *some* combination of auto-fill and manual correction. **Next session's first real check:** open a real LinkedIn job posting, compare what auto-fills against the page, and if anything's off, get the real selector via DevTools element-picker (same discipline as AbbVie's `css_selector` -- confirmed by hand, not guessed) rather than iterating blind.
- Similarly, the apply-link auto-extraction heuristic in `linkedin_extract.js` (looks for an anchor whose text matches `/company.?s?\s*(site|website)/i`) is unverified -- the user has been pasting the apply link in by hand each time so far, not confirmed whether auto-detection ever actually fires.

## 3. New feature discussed, scoped, NOT built -- LLM-assisted extraction

The user is finding manual LinkedIn extraction (even with the popup fix) still effortful per-posting, and wants to know if using an LLM to read/see the posting and auto-fill fields is worth building, especially across **multiple** postings in one sitting (the value case: if you're going to capture 10-20 postings in a session, even a moderately-reliable auto-extract saves real time over 10-20 manual fills).

This session **compared two shapes** without building either -- worth re-reading before picking one, not re-deriving from scratch:

- **Vision-model approach** (screenshot-based, `tabs.captureVisibleTab` + local Ollama multimodal model e.g. `qwen2.5vl:7b`) -- real and buildable, matches this project's existing local-Ollama-for-cheap-tasks pattern (`roles.yaml`), but has a genuine limitation: `captureVisibleTab` only grabs the visible viewport, not the full scrollable page, so a long job description would need multi-screenshot stitching or the user manually scrolling through a capture sequence.
- **Text-based approach** (grab the page's already-rendered text via the content script -- which is already extracting DOM content today, just via hand-guessed selectors -- send it to a local Ollama text model, ask for structured JSON fields back) -- simpler, no scrolling problem, cheaper/faster than vision, and arguably more direct: the job description is already real selectable HTML text, not an image that needs OCR-style reading.

**Not decided yet which to build, or whether to build either** -- the user chose to test the popup-window fix first and revisit this after. Live-testing step 1 above (checking the current hand-written selectors against a real page) should happen before scoping this further, since if the DOM selectors turn out mostly right with minor fixes, that may be enough on its own without an LLM in the loop at all -- worth checking cheap-fix-first before reaching for a heavier build.

If picked up next: a **multi-posting batch capture** angle is also worth considering alongside single-posting LLM extraction, given the user's own framing ("worth the time to do this" implies batch value, not one-off convenience) -- e.g. a "capture all visible job cards on a LinkedIn search-results page" mode, rather than only ever operating on one open posting at a time. Not scoped in any detail this session -- flagging as a shape worth asking the user about, not a decided direction.

## 4. Open items, updated

- **Pacific Biolabs 403** -- unchanged, still parked from `_4`/`_5`.
- **AbbVie pagination (session-cookie-based)** -- unchanged, still parked, root cause and fix shape already scoped in `_5`, don't rediagnose.
- **LinkedIn selector verification** -- new this session, see section 2 above. Real next step, before any further extension feature work.
- **LLM-assisted extraction (vision vs. text-based)** -- new this session, see section 3. Scoped as a comparison, not committed to either shape or to building it at all yet.
- **`db.py` was not uploaded this session** -- `migrate_add_apply_url.py` was written against a bare `sqlite3.connect()` rather than the project's real `get_connection()`, specifically because that interface wasn't available to confirm. If `get_connection()` does anything beyond opening the file (WAL mode, foreign-key pragmas, etc.), worth a quick check that the migration didn't need to account for it -- it ran successfully against the user's real DB per their own report, so this is a low-priority verification, not a known problem.
- **`schema.sql` still never uploaded in any session** -- same gap noted in the 2026-08-13 handoff for the repost-tracking feature, still true. Worth uploading if any future session needs to reason about the full real schema instead of inferring column shapes from `AST_OUTLINE.md`/live `PRAGMA table_info` checks, as this session had to.

## 5. Files to upload next session

**Must-have, if continuing the extension/LinkedIn-extraction work:**
- This handoff
- Current `dashboard.py` (this session's `apply_url` + capture-route + dropdown-fix changes are final as of this handoff)
- Current `biohunter-extension/` folder contents (popup-window + draft-autosave + apply-link changes are final as of this handoff)
- Whatever the user finds when checking `linkedin_extract.js`'s selectors against a real page in DevTools -- ideally the real class names, not just "it didn't work"

**If picking up LLM-assisted extraction specifically:**
- `roles.yaml` (to confirm the real current Ollama model routing/config before adding a new role to it)
- Nothing else new needed yet -- neither approach was started

**If finally resolving the long-standing schema gap:**
- `schema.sql` and `db.py` -- both still never uploaded in any session to date

## 6. Working style -- unchanged

Every claim above is backed by either the user's own live confirmation (screenshots, direct reports of what worked/didn't) or explicit code-level verification (`node --check`, `ast.parse`) -- and every place something is NOT yet verified live (the LinkedIn selectors, the apply-link heuristic, the `get_connection()` compatibility question) is flagged as such, not implied to be confirmed. Files handed back complete, never diffs, matching the user's vibe-coding workflow (edits saved and placed manually via their own environment, no Claude Code/IDE integration).
