# BioHunter — Jobsyn/Astellas Fix Confirmed Live, and a Zoomed-Out MVP Status Check

**Session date:** 2026-08-13 (same day as, and continuation of, `2026-08-13_BioHunter-GreenhouseFixConfirmed-RepostTracking-Handoff.md`, which this doc supersedes as the "read first" pointer for recent technical work — that doc's Greenhouse/repost-tracking details are still accurate and not repeated here).

**Why this doc is different from the usual handoff:** the user explicitly asked for this one to zoom OUT, not in — they've been deep in Scout/dashboard plumbing for several sessions and lost track of overall project state. **This doc's main job is answering "how close is BioHunter to a usable MVP, and what's the shortest path there" — read Section 1 first, before any of the technical detail below it.**

---

## 1. THE BIG PICTURE — read this first

**BioHunter's intended pipeline** (per ADR-0006 and the design doc, `docs/design/biotech-job-hunter-design.md`, not read this session but referenced by several ADRs):

```
Scout  →  Scorer  →  Writer  →  Critic  →  Revision  →  Report / PDF export
(find    (is this   (draft a   (review    (Writer<->   (human-readable
postings) posting    resume +   the        Critic loop  dossier +
          worth      cover      draft)     for N        submittable
          writing    letter)               rounds)      resume/cover-
          for?)                                          letter PDF)
```

**The core insight this session surfaced: this entire pipeline already exists and has worked end-to-end since 2026-08-04.** `docs/handoffs/2026-08-04-resume-pipeline-e2e-complete.md`'s own filename says so, and it's corroborated by real code:

- `scout/detector.py` — `run_scout()` discovers postings across 10 companies via ATS adapters (Workday, Greenhouse, Jobvite, Lever, Jobsyn) or fallback scraping. **Confirmed working live this session** (87 new postings from a real run).
- `scorer.py` — `score_posting()` triages postings against the candidate's actual Qdrant-stored background + `search_criteria.yaml` location/title preferences, before any resume gets written. Real, not stubbed — has its own debugged history (a model that silently returned malformed output was caught and swapped, per this file's own comments).
- `writer.py` + `selection.py` — `generate_draft()` runs a real 8-branch verbatim-selection pipeline (summary, intro, story, impact, gratitude, headings, bullets, skills) against the candidate's Qdrant catalog, with an explicit "select verbatim, never invent" constraint enforced in every branch's prompt. This is not a "call an LLM and hope" implementation — it's a deliberately constrained selection system.
- `critic.py` — `critique_draft()` does a real structured blind-review pass (6 fixed headers: ATS/keyword coverage, unsupported claims, weak bullets, weak summary, cover letter critique, overall recommendation + 1-10 score) against the drafted resume.
- `revision.py` — `run_revision_loop()` actually loops Writer → Critic → Writer-revision → Critic for N rounds, feeding critique back into regeneration.
- `report.py` — `render_posting_report()` produces a real self-contained HTML dossier (score dial, round-by-round diffs, full critique) — not a stub, has real CSS/layout already built.
- `resume_pdf.py` — `html_to_pdf_bytes()` via headless Chromium actually exports a submittable, ATS-conventional plain resume + cover letter PDF, separate from the dashboard-styled report.

**What every session since 2026-08-04 has actually been about — including this one — is NOT the core pipeline. It's been:**
1. Expanding *how many companies* Scout can reliably monitor (ATS adapter nuances: Workday 403s, Jobvite quirks, Greenhouse dead-link detection, and this session's Jobsyn/Astellas URL-construction bug).
2. Building a browser dashboard (`dashboard.py`) so the pipeline can be triggered/reviewed by clicking instead of running CLI commands — a convenience layer, not new capability (every dashboard action wraps an already-working CLI command: `run_scout`, `score_posting`, `run_revision_loop`).
3. Data hygiene: dead-link detection (postings that are no longer live), and this session's repost-turnaround-time tracking.

**None of #1-#3 are required for BioHunter to be personally usable end-to-end today.** You could, right now, run the CLI pipeline manually against real postings and get a real submittable resume PDF out the other end.

### What this means for "quickest path to MVP"

If MVP = "I can find real biotech postings and get a submittable, tailored resume + cover letter PDF out," **the honest answer is that MVP substance already exists** and has since 2026-08-04. What's actually missing, as far as this session's review could tell:

1. **Candidate name/contact info is never wired into the PDF export.** `resume_pdf.py`'s own comments say this explicitly: `render_resume_html()`/`render_cover_letter_html()` accept optional `candidate_name`/`contact_line` params and silently omit the header block if not given — nothing in this codebase currently sources that data (not Qdrant, not a config file, not the dashboard). **This is a real, concrete gap between "the pipeline works" and "you can actually submit what it produces."** Small fix (one new config field + wiring it through `cli.py`'s `cmd_report` and wherever the dashboard triggers PDF export), but it's not done.
2. **Visa sponsorship and salary fit are explicitly not scored** (`scorer.py`'s own comment says so) — not a bug, a documented scope limit, since no config or data source for either exists yet. Only matters if those are dealbreakers for this candidate; if not, this is fine to leave as-is indefinitely.
3. Whether the dashboard's "Generate" button actually calls the full real pipeline correctly end-to-end **has not been re-verified this session** — the outline confirms the wiring exists (`from .revision import run_revision_loop` etc. are real imports in `dashboard.py`), but nobody has done a fresh, full click-through (Scout → pick a posting → Generate → download PDF) recently, as far as this doc's author can tell from the handoff history.

**Recommended next-session focus, if the goal is closing the MVP gap rather than continuing to polish Scout:**
1. Do one real end-to-end run: Run Scout → pick one real posting → click Generate on the dashboard → download the PDF → actually read it. This either confirms MVP is done, or surfaces exactly what's broken in the dashboard-to-pipeline wiring that hasn't been exercised in a while.
2. If that works: wire in candidate name/contact info (the one clearly-known real gap).
3. Only after both of those: decide whether more ATS coverage, dead-link hygiene, or repost tracking are worth continued investment, or whether the project is "done enough" to just use.

---

## 2. This session's technical work (brief — see the superseded doc for repost-tracking/schema detail)

- **Jobsyn/Astellas URL-construction bug: found and fixed, confirmed live.** Root cause (via real API response data + a decompiled `.pyc` reconstruction, since the `.py` source wasn't available at first): when a posting lacked `location_exact` (common for international postings), the old code fell back to bare `city_exact` alone (e.g. `"bengaluru"`), producing a URL that looked valid but silently 404'd — no warning logged, unlike the already-handled "missing everything" fallback case. Fixed to combine `city_exact` + `country_short_exact` (`"bengaluru-ind"`), verified byte-for-byte against two real browser-confirmed URLs (one domestic, one international) before shipping. **User confirmed all 10 spot-checked Astellas postings from a real Scout run now resolve to real detail pages.**
- **Repost-tracking data model shipped** (schema columns + `detector.py` exact-title matching + turnaround-day computation) — see the previous handoff for full design rationale. No real repost data exists yet; nothing to check until a real repost happens on a future Scout run.
- **A new, unrelated observation surfaced and not yet acted on:** real Astellas job records from `prod-search-api.jobsyn.org` all show `"is_posted": false`. If that field means "not actually published yet," `jobsyn.py`'s `fetch_postings()` isn't filtering on it, and unpublished postings may be entering the DB as if live. **Not investigated further this session — flagging for whoever picks this up next.**
- **run_log's one error this run was expected, not new:** Scribe Therapeutics' Greenhouse board 404s (confirmed hard-gone in an earlier session, not a regression). Still blocked on finding an alternative monitoring approach (their real careers page is client-rendered).

---

## 3. Standing "still open, not touched" list (carried forward)

- **Scribe Therapeutics** — Greenhouse board confirmed hard-404'd. `scribetx.com/careers` is client-rendered; a plain `css_selector` scrape won't work. Needs either headless-render or finding the real underlying API the site calls. No new evidence this session.
- **Lever (Mammoth Biosciences)** — genuinely unverified, no known-dead posting to test dead-link detection against yet.
- **"Example Biotech Inc"** — stale leftover example data carried forward across many sessions; doesn't appear in the real `companies.yaml`. Should probably just stop being tracked as an open item.
- **Ashby** — confirmed not applicable; no Ashby company currently configured.
- **`is_posted: false` filtering question** (new this session, see above).
- **Candidate name/contact info wiring** (see Section 1 — this is the one that actually matters for MVP).

---

## 4. Working style — unchanged, still a hard default

The user vibe-codes this project: uploads files to a chat AI, the AI edits them, user downloads and drops the complete file into their local repo via VS Code/Git. **Every code change must be handed back as a complete downloadable file — never a diff, never a snippet, never prose describing the change.** This has been explicitly requested multiple times across sessions; treat it as non-negotiable, not something to rediscover.

Also carried forward: explain rationale before coding; check for existing logic before building new; verify actual output rather than trusting a change took effect; restart the dashboard process after any `.py` edit (editing alone does not affect an already-running `python -m biohunter.dashboard` process — this has caused confusion in nearly every session); spot-check real results by hand before trusting a bulk operation; a suspiciously clean number is worth investigating, not just a target hit.

**One new lesson from this session, worth carrying forward explicitly:** when a fix is described as applied but the same error recurs verbatim, the first thing to check is whether the file on disk actually got overwritten — not whether the fix itself was wrong. This session's `schema.sql` semicolon-in-comment bug was fixed correctly the first time, but the user's local file still had the old version for a follow-up message before it was caught by re-running a diagnostic script against the actual file content. A small `check_*.py` diagnostic script that reads and directly validates the real file in place (rather than trusting a description of what was sent) resolved it fast — worth reaching for that pattern again if something "already fixed" still fails.

---

## 5. Recommended files to upload next session

Only if picking up the MVP-completion thread from Section 1:
- **`docs/design/biotech-job-hunter-design.md`** — never read this session; would let the next AI confirm or correct the MVP definition above against what was actually originally scoped, rather than inferring it from handoff filenames and code comments.
- **`config/search_criteria.yaml`** and **`config/roles.yaml`** — referenced by `scorer.py`/`selection.py` but never uploaded; relevant if wiring in candidate contact info or investigating the visa/salary scope-limit further.
- **`cli.py`, `resume_pdf.py`, `dashboard.py`'s Generate route** (full source, not just outline signatures) — needed if actually doing the "one real end-to-end run" recommended above and something breaks.

If continuing the Scout/ATS-coverage thread instead: same files as the superseded handoff's own recommendations (`db.py` was already uploaded and reviewed this session; nothing new to add there).
