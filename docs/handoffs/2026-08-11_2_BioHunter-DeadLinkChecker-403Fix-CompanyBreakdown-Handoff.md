# BioHunter — Dead-Link Checker Confirmed Working, Workday 403 Signal Added, Recent-Jobs Page

**Session date:** 2026-08-11 (continuation, same day — supersedes `2026-08-11_BioHunter-DeadLinkChecker-ATSNuances-Handoff.md` as the "read first" pointer; that doc's §1–3 background is still accurate and not repeated in full here).

**One-line summary:** The Workday and Jobvite fixes from earlier today are now confirmed working end-to-end against a real, full sweep (221 confident dead links, 0 inconclusive — down from 4 dead / 313 inconclusive before the fixes and a process restart). A real, evidence-based new signal was added (Workday CXS returning HTTP 403 means the requisition is closed, confirmed against Genentech/Gilead postings by hand). Two small dashboard usability additions closed real friction hit during testing: a per-company breakdown on the Dead tab, and a `/jobs` "recent jobs" index so a results page is never un-recoverable again.

---

## 1. What actually got confirmed this continuation

**The stale-process gotcha was real, not a code bug.** After the Jobvite fix (§ of the prior handoff) was written, a rerun still showed BioMarin postings blocked by `robots.txt disallows checking this URL` — identical to pre-fix behavior. `grep` confirmed the fix WAS present in the actual file on disk. The cause: the running `python -m biohunter.dashboard` process still had the old module loaded in memory. **A full stop/restart of the dashboard process was required** — editing the file alone did not take effect. Worth remembering for any future scraper.py/dashboard.py change: restart before concluding a fix didn't work.

**After the restart, one sweep: 1018 checked, 221 confident dead, 0 inconclusive.** Zero inconclusive is itself a meaningful data point — it means Greenhouse/Lever/Ashby's public posting pages are NOT blocked by robots.txt either (if they were, some of their postings would still be showing up inconclusive). This is *indirect* confirmation for those three platforms, not a direct one — nobody has yet seen a `detail` string proving what a genuinely dead Greenhouse/Lever/Ashby posting looks like; it just means nothing about checking them is currently broken.

**A real, new signal found and shipped — Workday CXS HTTP 403 means "closed requisition":** Before the restart/full sweep, spot-checking Genentech and Gilead's *inconclusive* entries (same tenant, `roche.wd3.myworkdayjobs.com`) turned up a clean, opposite-direction split:
- `HTTP 403 from Workday CXS` → clicking the real public posting confirmed **dead** ("the page you are looking for doesn't exist"), every time checked.
- `Workday CXS request failed: ... Read timed out` → clicking the real public posting confirmed **alive** (real job description present), every time checked.

Fixed in `_check_workday_url_alive()`: HTTP 403 now returns `(False, ...)` — lands on the checkbox-confirmed Dead tab, same human-in-the-loop safety net as every other Dead entry, nothing auto-written. Timeouts are left untouched (still inconclusive) since the data supports leaving them ambiguous, not claiming them alive outright.

**Real spot-check validation of the full 221:** more than 20 postings clicked by hand across the batch, **all** confirmed genuinely dead ("does not exist" on the real site). Rough per-company breakdown recalled from browser history: Amgen 23, BioMarin 43, Denali 6, Genentech 112, Gilead 17, Guardant 19 (self-reported as approximate/miscounted by hand — see the new feature below for an exact count going forward).

**Posting 579 is correctly absent from the 221** — not a miss, it was manually marked stale earlier this session before this final sweep ran, so it's excluded by the query (`WHERE postings.status != 'stale'`) by design.

---

## 2. New this continuation

**`scraper.py`:** `_check_workday_url_alive()` gained an explicit `resp.status_code == 403` branch, returning confident-dead with a docstring citing the real Genentech/Gilead evidence above. Explicitly commented to downgrade back to inconclusive if this stops correlating at scale — this is evidence-based, not proven exhaustively.

**`dashboard.py`:**
- Per-company breakdown card at the top of the Dead tab (`collections.Counter` over the in-memory `dead` list, sorted highest-first) — added directly after a real session where hand-counting from a browser-history page produced an approximate, slightly-off count.
- New `/jobs` route (`jobs_index()`) listing every job the current dashboard process has run, newest first, each linking back into its results/status page. Added directly after this session hit exactly this gap: an accidental click navigated away from a finished dead-link-check results page with no way back except browser history or the Flask console log. Still memory-only (`_jobs` dict) — a dashboard restart clears it, same limitation as every other job result in this file, just no longer a dead end while the process is alive.
- "Recent jobs" link added to the postings-index header next to "Run Scout" / "Check for dead links".

---

## 3. Still open — not yet confirmed, don't assume done

- **Was "Mark checked posting(s) as stale" actually submitted for the 221?** Not confirmed in this conversation — the spot-checking happened, but no message confirms the mark-stale form was submitted afterward. Check `SELECT COUNT(*) FROM postings WHERE status='stale';` before and after clicking submit to confirm the write landed, same discipline used everywhere else this session.
- **Greenhouse/Lever/Ashby are indirectly, not directly, confirmed.** 0 inconclusive across the whole sweep is reassuring but nobody has looked at a `detail` string for a genuinely dead posting on any of these three platforms specifically. If one ever surfaces in a future Inconclusive tab (should stay empty if today's read is right, but worth remembering why it would matter if it isn't).
- **Jobsyn (likely Astellas)** — untouched this continuation. Still a URL-construction reliability problem, not a robots.txt/redirect issue; see the prior handoff §3. Do not trust Jobsyn dead/alive results from this feature.
- **Scribe Therapeutics** (carried forward two sessions now) — confirmed the Greenhouse public API is disabled for this board specifically; needs `companies.yaml` switched to `css_selector` scraping against `scribetx.com/careers`. `companies.yaml` still never uploaded across three sessions.
- **"Example Biotech Inc"** (carried forward two sessions) — NULL `last_checked_at` row, likely stale example data. Still never confirmed via the two diagnostic queries requested.

---

## 4. Files touched this continuation (full current state)

```
src/biohunter/scout/scraper.py    added: HTTP 403 branch in _check_workday_url_alive()
src/biohunter/dashboard.py        added: collections import, per-company breakdown on
                                   dead_links_results(), jobs_index() route + /jobs page,
                                   "Recent jobs" header link
```
No other files changed this continuation.

---

## 5. Recommended files to upload next session

Same as the prior handoff's §6 — still unresolved:
```
config/companies.yaml   (still never uploaded across three sessions; needed for Scribe
                          Therapeutics' fix and to know which companies sit on which ATS)
```
Plus current-state files if continuing dead-link work:
```
src/biohunter/scout/scraper.py, dashboard.py   (this handoff's versions)
```

---

## 6. Working Style

Carried forward, reinforced again:
- **Verify actual output, don't trust that a code change took effect** — the BioMarin/Jobvite "fix that didn't work" was actually a fix that hadn't been loaded yet (stale process). `grep`-confirming the fix was ON DISK, then still seeing old behavior, was the signal to check the running process next, not to doubt the fix itself.
- **Spot-check before bulk-confirming a state change**, especially the first time a new heuristic (the 403 signal) is running for real. 20+ real clicks confirming all-dead before trusting the full 221 is exactly right — cheap insurance against a bad batch write.
- **A number that's suspiciously clean (0 inconclusive) is itself informative**, not just a target hit — it's indirect evidence about the platforms that were never directly tested, worth naming explicitly rather than filing away silently as "worked fine."
