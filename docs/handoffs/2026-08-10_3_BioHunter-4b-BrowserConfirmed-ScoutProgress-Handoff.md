# BioHunter — 4b Confirmed Working, Real Scout Progress Wired, Cleanup

**Session date:** 2026-08-10 (third session this date — continuation of
`2026-08-10_BioHunter-PreFilter-ScorerModelFix-DashboardButtons-Handoff.md`,
which this doc supersedes as the "read first" pointer).

**One-line summary:** 4b is no longer "written, not confirmed" — both
dashboard buttons were run for real and work. Scout's dashboard progress
went from an honest placeholder to real per-company data, using a
callback param (`on_company_done`) that turned out to already exist in
`detector.py`. One stale comment fixed. Scribe Therapeutics's 404
narrowed down but not solved — needs a browser, not more guessing.

---

## 1. What happened, in order

**4b confirmed working in a real browser** — the single most important
open item from the prior handoff. "Run Scout" found 6 new postings
(936→942) with one error (Scribe Therapeutics, see below — a known,
pre-existing gap, not a new one). "Score filtered postings" scored 7
postings against the Bay Area/title-filtered set. Rationales for the 6
new postings were sound (correctly penalized non-Bay-Area locations —
Tokyo, India, China — and role mismatches like sales/finance/manufacturing
pivots against a research-scientist background).

**An apparent anomaly turned out not to be one.** After the scoring run,
`postings` status counts looked inconsistent with a scoring-only action
(`new` count went *up*, a `stale` status appeared for the first time).
Root-caused via `run_log`, not guessed: the user had clicked "Run Scout"
three times total across the session, and the third click landed *after*
the scoring step — fully explains both the count jump and a `stale`
posting (a Phase-1-era posting, first seen ~July 26-29, finally crossing
the 30-day `STALE_AFTER_DAYS` threshold on a successful company scan —
this looks like the first real case of that logic ever firing).

**`detector.py` uploaded, and it already solves the Scout-progress
gap.** `run_scout()` has an `on_company_done: Callable[[ScoutResult],
None] | None` parameter — its own docstring states it was added
specifically to close this exact dashboard gap. Wired it into
`dashboard.py`'s `_run_scout_job()`: the job dict now tracks
`companies_done`, `total_companies` (from `load_companies()` up front),
`new_postings_so_far`, and `current_company`, updated live as each
company finishes. The job-status page's polling JS now shows real
"Checked N of M companies — last: <company> — K new posting(s) so far"
instead of the previous generic "running, no fine-grained progress"
message. **Not yet re-tested in a browser after this specific change** —
same "written, not confirmed" caveat 4b itself just came out of; worth
clicking "Run Scout" once more to confirm the new progress text
actually renders as intended.

**`roles.yaml`'s `critic_review` comment fixed.** Previously said
"Routed to Anthropic on the same reasoning as writer_coverletter and
networker_email_draft," while the actual config underneath has always
been `provider: ollama, model: gemma4:12b-mlx` — same class of
comment/config drift as `scorer_fit`'s own comment, fixed earlier this
date. Comment now states the real, current config and why it's
reasonable (gemma4:12b-mlx already proven for structured output
elsewhere), rather than asserting a routing that was never actually true.

**Scribe Therapeutics's Greenhouse 404 — narrowed, not solved.** Their
real careers page has moved to `scribetx.com/careers` (company now
brands as "Scribe," not "Scribe Therapeutics" — still the same CRISPR
company, Doudna-founded, South San Francisco/Alameda). That page's job
listings render via client-side JS — a static fetch only sees an
"Openings" heading and a `[Job title]` placeholder link, no actual
postings or board token. Third-party aggregators are inconclusive:
Built In currently shows zero open roles; another aggregator (BuiltIn's
data may simply be stale) showed 2 real bioinformatics postings
elsewhere. **Can't determine the real Greenhouse board token (if any)
without a browser** — someone needs to open `scribetx.com/careers`,
open browser devtools' Network tab, and see what URL the job list
actually calls (or confirm it's moved to a different ATS entirely,
which the current `boards-api.greenhouse.io/v1/boards/scribetherapeutics/jobs`
404 might indicate). Once that's known, it's a one-line
`companies.yaml`/`ats_slug` fix, matching the class of fix this project
already knows how to do.

---

## 2. Files touched this session

- `src/biohunter/dashboard.py` — `on_company_done` wired into
  `_run_scout_job()`; `load_companies` import added; job-status page's
  scout-branch JS updated to show real progress; module docstring
  updated to reflect the resolved gap.
- `config/roles.yaml` — `critic_review`'s stale comment fixed (config
  itself was already correct, comment was wrong).

No files added or removed — `docs/FILE_TREE.txt` unaffected.

---

## 3. Open items to confirm at the start of next session

- **Re-test "Run Scout" once more** to confirm the new per-company
  progress text (`companies_done`/`total_companies`/`current_company`/
  `new_postings_so_far`) actually renders correctly in the browser —
  this specific change was written but not re-verified live.
- **Scribe Therapeutics** — needs someone to open
  `https://www.scribetx.com/careers` in a real browser, check the
  Network tab for the actual jobs API call, and report back the real
  board/ATS so `companies.yaml` can be corrected. Can't be resolved by
  search/fetch alone (JS-rendered content).
- Carried forward, unchanged, still blocked on files not yet uploaded:
  `jobvite.py`'s `_DESCRIPTION_SELECTORS` still unverified against real
  HTML (works 116/153 in practice, never confirmed why); `companies.ats_type`
  staleness in the DB (the Denali example) unfixed in
  `_get_or_create_company_id()`.
- Carried forward from two sessions ago, still unresolved: the Guardant
  Health "Sr. Client Services Specialist" posting's rationale claimed a
  location mismatch on a posting that had already passed the location
  filter — a query was handed to the project owner to check the
  posting's real stored location, but the result was never reported
  back. Worth closing this loop before trusting location-reasoning
  across the other 191 rationales.

---

## 4. Recommended files to upload next session

Core (current state, needed to continue):
```
src/biohunter/dashboard.py     (on_company_done now wired, needs one more browser confirm)
config/roles.yaml              (both scorer_fit and critic_review comments now accurate)
```
Still needed, blocking real fixes (asked for across three sessions now):
```
src/biohunter/ats/jobvite.py       (to verify/fix _DESCRIPTION_SELECTORS)
src/biohunter/detect_ats.py or wherever _get_or_create_company_id-adjacent
    ats_type detection lives (to fix companies.ats_type staleness)
```
Reference:
```
this file
2026-08-10_BioHunter-PreFilter-ScorerModelFix-DashboardButtons-Handoff.md (prior session)
```

---

## 5. Working Style

Same standing rules as always. One more concrete instance of the
existing "verify, don't guess" pattern this session: rather than
assuming `run_scout()` had no progress-reporting hook (the honest
placeholder from last session), the actual uploaded `detector.py` was
read first — and it turned out the hook already existed, added the same
day specifically for this purpose. The lesson isn't new, but it's worth
restating plainly: an "I don't have this file, so I won't guess" gap
from one session can turn into a five-minute wire-up the next, once the
real file shows up. Worth treating "still blocked on missing file X" as
a standing to-do to actually upload X, not a permanent state.
