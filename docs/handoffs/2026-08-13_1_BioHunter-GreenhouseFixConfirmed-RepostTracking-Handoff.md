# BioHunter — Greenhouse Dead-Link Fix Confirmed Live, Jobsyn Still Blocked, Repost-Tracking Feature Requested

**Session date:** 2026-08-13 (continuation of `2026-08-11_2_BioHunter-DeadLinkChecker-403Fix-CompanyBreakdown-Handoff.md`, which this doc supersedes as the "read first" pointer; that doc's background on Workday/Jobvite is still accurate and not repeated here).

**One-line summary:** The Greenhouse dead-link fix (drafted last session from real Nurix evidence, but not yet applied/tested) is now confirmed working end-to-end against real data — 24 Nurix postings correctly identified as dead and marked stale, including one the user manually double-checked and found genuinely absent from the board despite a 200 response. A real pre-existing bug in `dashboard.py`'s `dead_links_results()` was found and fixed along the way (only triggered once Greenhouse started returning non-empty dead results for the first time). Jobsyn/Astellas work remains blocked on real sample data. New feature requested: track repost turnaround time (how long between a posting going stale and the same role reappearing) — not yet built, spec'd below.

---

## 1. What got confirmed this session

**The `_check_greenhouse_url_alive()` fix (drafted last session) works, verified two ways:**
- Applied to `scraper.py`, dashboard process restarted (the same stale-process gotcha from the 2026-08-11 handoffs — editing the file alone does not take effect on a running `python -m biohunter.dashboard` process).
- Ran "Check for dead links." User manually clicked through every flagged entry. All non-Nurix entries showed a clean "job no longer exists" message. **Nurix entries were different in a specific, informative way**: instead of a 404 or an explicit "not found" message, the response was the board's own live listing page (HTTP 200, looks like a normal page) — but the specific job title was genuinely absent from it. This is a live, human confirmation of the exact `error=true`-redirect-to-board-root signature this fix was built around from web-fetched evidence last session — real data now backs what was previously inferred from two externally-fetched job IDs.
- User submitted "mark checked postings as stale" for the batch: **24 of 24 confirmed stale in the DB**, per the results page's own post-write re-query (not just the in-memory job snapshot — see `dead_links_results()`'s docstring on why that distinction was built in). This also closes the long-open "was the mark-stale write ever actually confirmed" question from the 2026-08-11 handoffs — it was, this time, directly.

**A second, pre-existing bug found and fixed along the way (in `dashboard.py`, not caused by this session's `scraper.py`/`jobsyn.py` changes):**
`dead_links_results()` (around line 963–966) built its "already stale" re-check query with a **list** as the parameter argument:
```python
rows = conn.execute(
    f"SELECT id FROM postings WHERE status = 'stale' AND id IN ({placeholders})",
    [d["id"] for d in dead],
)
```
This raised `TypeError: argument 'parameters': 'list' object cannot be converted to 'PyTuple'` the first time `dead` was non-empty for a Greenhouse-sourced batch. It very likely would have thrown on ANY non-empty `dead` list, including the original 221 Workday/Jobvite entries — but that code block's own docstring says it was "added after a real session" (i.e., added later, possibly never actually exercised with real data before now). Whatever DB connection layer `get_connection()` returns is stricter about parameter types than plain `sqlite3` normally is (worth checking `db.py` — possibly `apsw` rather than stdlib `sqlite3`, given the exact `PyTuple` wording in the error). **Fix**: wrap in `tuple(...)` instead of a list comprehension producing a list. User applied this directly via VS Code/Git rather than via a pasted file. Confirmed working (see above — the sweep completed and results page loaded cleanly after this fix).

---

## 2. Still blocked — Jobsyn / Astellas

Two diagnostic-only changes were made to `jobsyn.py` and `scraper.py` this session (not a real fix — see prior handoff for why):
- `jobsyn.py`'s `_to_raw_posting()` now logs a warning naming which field (`location_exact`/`city_exact`, `title_slug`, or `guid`) was missing whenever it falls back to the bare `{origin}/jobs/` root URL.
- `scraper.py`'s `check_url_alive()` dispatcher now treats any URL with path exactly `/jobs/` as inconclusive rather than running the generic check (which would always read HTTP 200 → "alive" against the bare site root, a guaranteed false positive).

**Neither has been confirmed applied or tested this session** — user's focus was the Greenhouse fix and the dashboard bug. Still needed before the real URL-construction problem can be fixed: 2-3 real Astellas posting rows (`title_exact`, `location_exact`, `title_slug`, `guid`) pulled via a browser Network tab against `astellascareers.jobs` — the site is entirely client-rendered and its search API isn't reachable by web search/fetch tools, so this has to come from the user directly, same method that originally cracked the Workday and Jobvite bugs.

---

## 3. New feature request — repost turnaround-time tracking

**User's ask:** companies sometimes repost a role after it goes stale; user wants to know the turnaround time (how long between "marked stale" and "same role reappears").

**Current behavior, confirmed by reading `detector.py`:** `_upsert_postings()` matches an incoming posting to an existing DB row by exact `(company_id, url)` only. Since a repost on most ATS platforms gets a **new URL** (new Workday `externalPath`, new Greenhouse job ID, etc.), a repost currently inserts as a brand-new, unrelated row — it does NOT revive or link back to the stale row. **Nothing currently computes or stores a turnaround time.** This needs to be built, not just enabled.

**Not yet built — needs, in order:**
1. **Check `schema.sql`** (not uploaded this session) for whether `postings` has a `first_seen_at`/`created_at` column distinct from `last_seen_at`, and whether there's any existing `stale_at`/status-change-timestamp tracking. Without a "when did this go stale" timestamp, turnaround can't be computed even after matching reposts.
2. **Matching strategy**: exact URL matching won't catch reposts by definition. Likely needs a secondary match on `(company_id, normalized_title)` — possibly exact title match to start (cheap, low-false-positive-risk), with fuzzy matching as a stretch goal if titles vary slightly between original and repost.
3. **Design question to resolve with the user before coding**: should a detected repost (a) update the existing stale row back to active status and log the gap, or (b) stay as two separate rows (old stale one preserved as history, new one inserted normally) with a link/reference between them? Option (b) is safer for not silently mutating historical data Critic/Writer may have already used, but needs a new column or join table to store the link.
4. Once schema is settled: `_upsert_postings()` gains a repost-detection branch, run only when a normal URL-match misses AND the incoming title matches a `company_id`-scoped stale row.

**Recommend starting next session by uploading `schema.sql`** — this whole feature is blocked on knowing the real current schema, not guessable from the files already seen.

---

## 4. Files touched this session (full current state)

```
src/biohunter/scout/scraper.py    _check_greenhouse_url_alive() added + wired into
                                   check_url_alive()'s dispatcher; /jobs/-path
                                   inconclusive check added (applied + confirmed working)
src/biohunter/ats/jobsyn.py       _to_raw_posting() fallback-path warning logging added
                                   (applied, NOT yet confirmed tested)
src/biohunter/dashboard.py        dead_links_results(): list -> tuple(...) fix for the
                                   already-stale re-check query (applied directly by user
                                   via VS Code/Git, confirmed working via live sweep)
```

---

## 5. Recommended files to upload next session

```
config/schema.sql        -- never uploaded any session so far; blocks the repost-tracking
                             feature entirely, needed to know what columns already exist
src/biohunter/db.py       -- never uploaded; would explain the get_connection() PyTuple
                             strictness (stdlib sqlite3 accepts lists fine in isolated
                             testing -- something about this project's connection layer
                             doesn't). Not urgent to fix further (tuple() fix works either
                             way) but worth understanding if similar bugs are suspected
                             elsewhere in dashboard.py's other conn.execute() calls.
```
Plus, if picking up Jobsyn again: 2-3 real Astellas posting rows (title_exact/location_exact/title_slug/guid) via browser Network tab -- paste as text, not a file.

If picking up Scribe Therapeutics: still needs a different approach than the previously-proposed css_selector scrape (scribetx.com/careers's "Openings" section is client-rendered, confirmed via web fetch last session) -- no new evidence gathered this session.

---

## 6. Still open, carried forward, not touched this session

- **Lever (Mammoth Biosciences)** — genuinely unverified. No dead-posting evidence found in any session so far; no known-dead Lever posting ID to test against yet.
- **Scribe Therapeutics** — whole Greenhouse board confirmed hard-404'd (not one posting). Proposed fallback (css_selector scrape of scribetx.com/careers) likely won't work as-is (client-rendered page). Needs either a headless-render approach or finding the real underlying API scribetx.com's site actually calls.
- **"Example Biotech Inc"** — carried forward across many sessions now, still never confirmed via diagnostic queries. Likely stale leftover example data (further supported by: it does not appear anywhere in the real, now-uploaded `companies.yaml`).
- **Ashby** — confirmed NOT applicable. No Ashby company is currently configured in `companies.yaml` at all; this should stop being carried forward as an "unverified" open item.

---

## 7. Working Style — carried forward, plus one new instruction for the next session

Standing rules, unchanged: explain rationale before coding; check for existing logic before building new; verify actual output, don't trust that a code change took effect (restart the dashboard process after any scraper.py/dashboard.py/jobsyn.py edit); spot-check real results by hand before trusting a bulk batch; name a scope/behavior reversal explicitly when it happens; a suspiciously clean number (0 dead, 0 inconclusive) is itself informative and worth investigating, not just a target hit.

**New, important for how to work with this user specifically:** the user is "vibe coding" — they do not use Claude Code or an IDE-connected AI integration. They work by uploading files to a chat AI, having the AI make the edits, and downloading the fully-edited file back to place directly into their local project via VS Code/Git. **For any code change, the next AI session should produce and hand over the complete edited file(s) as downloadable output, not diffs, not prose descriptions of changes, and not partial code snippets asking the user to paste them in manually.** The user has explicitly pushed back on being handed copy-paste snippets before, expecting full-file downloads instead — this preference should be treated as a hard default for this project, not something to rediscover mid-session.
