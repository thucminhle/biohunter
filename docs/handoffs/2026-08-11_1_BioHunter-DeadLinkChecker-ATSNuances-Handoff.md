# BioHunter — Dead-Link Checker Built, Two ATS Fixes Confirmed, Three Platforms Still Unverified

**Session date:** 2026-08-11 (continuation of `2026-08-10_2_BioHunter-PreFilter-ScorerModelFix-DashboardButtons-Handoff.md`, which this doc supersedes as the "read first" pointer).

**One-line summary:** A dead-link check feature (single-posting button + whole-DB sweep, with Dead/Inconclusive result tabs) got built, then immediately caught two real, previously-invisible platform blind spots — Workday's SPA shell always returning HTTP 200, and Jobvite's robots.txt blocking the public page entirely while soft-redirecting dead postings to a 200 page. Both are fixed and verified against real postings. Ashby/Greenhouse/Lever are still unverified — the same "check the real output" method that found the first two bugs is the recommended next step, not more guessing.

---

## 1. What shipped this session, in order

**Prior-session closeout, now confirmed in a real browser (not just `py_compile`):**
- Guardant Health's "location mismatch" scoring rationale was checked and confirmed CORRECT — the model was catching a real distinction (`Remote-USA-MA`/`TN` vs `Remote-USA-CA`) a substring filter can't see. Not a bug.
- `detector.py`'s `run_scout()` gained an optional `on_company_done` callback so the dashboard's "Run Scout" button could show real per-company progress instead of an honest placeholder. **Confirmed ticking live in a real run** (10 companies, staggered timestamps 13 minutes apart, matching a real company-by-company pass).
- Posting 622's NULL score (a `scorer_fit` parse miss) was diagnosed via a standalone read-only debug script — confirmed **intermittent, not systemic** (the same model produced a clean, well-formed response on a fresh call). Fixed with one manual `UPDATE` using that real captured score/rationale, since the diagnostic script deliberately never writes to the DB itself.

**New this session — the dead-link checker:**
- `scout/scraper.py`: `check_url_alive(url, limiter)` — generic check (HTTP 404/410 = dead, 200 = alive, anything else = inconclusive), still the fallback path for any host not special-cased.
- `dashboard.py`:
  - Single-posting **"Mark as stale (link is dead)"** button on `posting_detail()`, next to the "original posting" link — the direct answer to "I clicked through and it's a 404, how do I fix this without raw SQL."
  - Whole-database **"Check for dead links"** button on the postings index — same background-job/live-progress pattern as Scout and Score-batch (`kind="dead_link_check"`).
  - Results page at `/postings/dead-links/<job_id>` with two tabs: **Dead** (confident hits, checkboxes, submits to the one route — `POST /postings/mark-stale` — that actually writes `status='stale'`) and **Inconclusive** (read-only, added specifically so a large "not shown" number isn't invisible).

**First real run: 947 checked, 0 dead, 153 (16%) inconclusive.** Zero dead links on a brand-new feature built specifically because a dead posting existed (Amgen's TEPEZZA case manager posting, id 579) was the red flag that something was wrong, not evidence the feature worked.

**Root cause #1 — Workday, CONFIRMED and FIXED:** Fetching the real dead TEPEZZA posting's public URL directly (`web_fetch`) returned a normal HTTP 200 — Workday's public job page is a client-rendered SPA shell that returns the same 200 whether the job exists or not; the real "gone" message only appears after browser JS calls Workday's internal API. Fix: `_check_workday_url_alive()` reuses the exact CXS detail endpoint `ats/workday.py`'s own `_fetch_description()` already calls (derived straight from the stored URL, no company-config lookup), and treats a 200-with-empty-`jobPostingInfo` response as dead — reusing a signal `workday.py` already logs a warning for but never acted on.

**Second real run: 1018 checked, 4 dead, 313 (31%) inconclusive** — inconclusive nearly doubled instead of dropping, the opposite of what a working fix should do.

**Root cause #2 — Jobvite, CONFIRMED and FIXED, via two real screenshots the user provided (BioMarin postings):** Both a genuinely-dead posting and a genuinely-alive posting showed the identical detail string `"robots.txt disallows checking this URL"`. Confirmed against real `ats/jobvite.py` source: that adapter's own `fetch_postings()`/`_fetch_description()` hit this exact same public URL directly via plain `requests.get()`, **no robots.txt check anywhere** — meaning the dead-link checker was stricter than Scout's own real scraping of the identical page. Separately (would have mattered even without the robots issue): a dead Jobvite posting doesn't 404 — it redirects to a generic `.../jobs?error=404` listing page that itself returns 200, confirmed via the same screenshots. Fix: `_check_jobvite_url_alive()` skips robots.txt for `jobs.jobvite.com` (mirroring `jobvite.py`'s own real behavior) and checks the *final* URL's query string for `error=404` after following redirects, rather than trusting the status code alone.

The **Inconclusive tab is what made both of these findable** — a discarded count would have hidden the exact evidence (identical detail strings on a dead and a live posting) that proved the root cause.

---

## 2. Where each ATS platform actually stands — confirmed vs. guessed

| Platform | Status | Real evidence |
|---|---|---|
| Workday | **Fixed** | 1 real posting (TEPEZZA/Amgen), confirmed via direct fetch |
| Jobvite | **Fixed** | 2 real postings (BioMarin), confirmed via user screenshots |
| Greenhouse | **Unverified** | One data point exists (Scribe Therapeutics), but that was a whole-board API outage, not a single pulled job on a working board — different failure mode, proves nothing about normal dead-posting behavior |
| Lever | **Unverified** | Adapter fetches `api.lever.co` (JSON); stores `job.hostedUrl` (`jobs.lever.co`, public page) — different host, no precedent either way |
| Ashby | **Unverified** | Same host-mismatch as Lever (fetches `api.ashbyhq.com`, stores `job.jobUrl` on `jobs.ashbyhq.com`). Ashby boards are modern SPAs in practice — worth specifically checking for a Workday-style soft-200, not just a robots block |
| Jobsyn (likely Astellas) | **Different problem entirely** — see §3 | — |

**Important nuance for whoever picks up Greenhouse/Lever/Ashby:** for Workday and Jobvite, the adapter's own real fetch happened to hit the *same* URL the dead-link checker tests, so "does the adapter check robots" directly answered "should the checker." For Greenhouse/Lever/Ashby, the adapter fetches a JSON API host, while the checker tests the separate public-page host — that precedent does **not** transfer automatically. Don't assume; check the actual host being tested.

## 3. Jobsyn — not a robots.txt/redirect problem, a URL-construction reliability problem

`ats/jobsyn.py`'s `_to_raw_posting()` doesn't get a URL from the API — it constructs one from a slugified `location_exact` + `title_slug` + `guid`, and **falls back to the bare `{origin}/jobs/` root** when any piece is missing (the adapter's own comment admits this happens for some international postings). Consequences for THIS feature specifically:
- A posting that fell back to the generic root will read as "alive" (200) regardless of that job's real status — it's not actually checking that job.
- A posting whose slug was constructed slightly wrong could 404 even though the real job is still live elsewhere on the site.

**Don't build a bespoke `_check_jobsyn_url_alive()` yet.** The fix needed here is upstream — verifying/improving the URL construction itself against real Astellas data — separate, real work, not a quick addition to `check_url_alive()`.

---

## 4. Suggested next steps, in order

1. **Run the dead-link sweep again** (safe, read-only, no DB writes either way) and open the Inconclusive tab. Pull the exact detail string for a few entries from Greenhouse/Lever/Ashby-sourced companies (cross-reference `config/companies.yaml`'s `ats_type` if unsure which company is which — not yet uploaded this session). This is the same method — real evidence, not speculation — that found both fixes above.
2. Depending on what that shows, per platform it'll be one of:
   - robots.txt blocks the public page too → same fix pattern as Jobvite (skip robots, since the adapter itself may not check it either — verify first)
   - a real 404/410 → the existing generic logic already works, no fix needed
   - a third soft-fail pattern not yet seen → needs its own bespoke signature, same spirit as Jobvite's `error=404` check
3. Separately, lower priority: investigate Jobsyn's URL-construction reliability (§3) before trusting any of its results.
4. **Scribe Therapeutics** (carried from last session): confirmed the Greenhouse public API is disabled for this board specifically, not a slug typo. Needs `companies.yaml` switched from `ats_type: greenhouse` to a `css_selector` scrape against `scribetx.com/careers`, if desired. Not done — `companies.yaml` never uploaded this session.
5. **"Example Biotech Inc"** (carried from last session): a NULL-`last_checked_at` row in `companies`, likely leftover example data. Never confirmed via the two diagnostic queries requested last time. Still open.
6. Posting 579 (the original TEPEZZA case that started this whole thread) should now be catchable via a fresh sweep with the Workday fix live — worth confirming it lands in the Dead tab.

---

## 5. Files touched this session (full current state, not incremental)

```
src/biohunter/scout/scraper.py    check_url_alive() dispatcher + generic 404/410 path,
                                   _check_workday_url_alive(), _check_jobvite_url_alive()
src/biohunter/scout/detector.py   run_scout() on_company_done callback (confirmed working)
src/biohunter/dashboard.py        posting_detail() mark-stale button; check-dead-links /
                                   dead-links results (Dead+Inconclusive tabs) / mark-stale
                                   routes; _run_dead_link_check_job(); job_status_page JS
                                   extended for kind="dead_link_check" and kind="scout"
```
One direct DB write outside any code path: `postings.score`/`score_rationale` for id=622, via manual `UPDATE` using a real score captured from a one-off diagnostic script run.

No changes to `config/roles.yaml` or `src/biohunter/scorer.py` this session (resolved last session).

---

## 6. Recommended files to upload next session

Core, to continue the ATS-nuance investigation:
```
config/companies.yaml                          (never uploaded this whole session --
                                                 needed to know which real companies sit
                                                 on Greenhouse/Lever/Ashby/Jobsyn)
```
Plus: whatever Inconclusive-tab detail strings a fresh sweep turns up for Greenhouse/Lever/Ashby entries (paste text, not a file).

If pursuing Jobsyn: real sample Astellas posting URLs + their jobsyn.py-constructed equivalents, to compare directly.

If pursuing Scribe Therapeutics: `config/companies.yaml` (same file, also needed here).

Reference (already seen this session, current state reflected above):
```
src/biohunter/scout/scraper.py, dashboard.py, detector.py
src/biohunter/ats/{workday,jobvite,ashby,greenhouse,jobsyn,lever}.py, base.py
```

---

## 7. Working Style

Same standing rules as always: explain rationale before coding; check for existing logic before building new; avoid unnecessary abstraction; favor incremental testable milestones; name a scope/behavior reversal explicitly when it happens; no auto-submit/no auto-send.

Two lessons already carried from the prior handoff, reinforced hard again this session:
- **Verify actual output before trusting what code "should" do.** Both real bugs this session (Workday's SPA shell, Jobvite's robots.txt block) were invisible from source code alone and only surfaced by fetching real URLs and reading real screenshots of the app's own output.
- **A file that passes `py_compile` is not a file that's been tested.** True of this session's dead-link feature the same way it was true of last session's dashboard buttons.

One NEW lesson worth carrying forward hard from this session specifically:
- **A safety check you add yourself (robots.txt, in this case) can end up stricter than the very system it's validating, if it's not checked against what that system's real code path actually does.** "Be polite by default" sounds responsible but isn't automatically correct — check what Scout's own adapter does with that exact URL before importing an extra constraint the adapter never had. This cost real accuracy twice in one session, and the first real run showing 0 dead links out of 947 was itself the signal to stop and investigate immediately, not explain away as "the data's just clean."
- **Adapter-fetched URL and stored/displayed URL are not always the same host.** Ashby/Greenhouse/Lever all fetch a JSON API but store/display a different public page's URL. "Does the adapter check robots on its own fetch" does not automatically answer "is the stored URL blocked" — those can be two different hosts with two different rules. Check the actual host being tested, not just the adapter's internal fetch target.
