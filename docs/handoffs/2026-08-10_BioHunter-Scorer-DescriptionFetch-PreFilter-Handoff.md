BioHunter — Scorer Agent, Multi-ATS Description Fetch Fixes, Pre-Score
Filtering Handoff (2026-08-10)

Project Summary

BioHunter is a self-hosted, local-first AI platform that automates biotech
job searching and application preparation.

Pipeline:

Scout
    ↓
Scorer          <- BUILT THIS SESSION (see section 1a) — was "NOT YET BUILT"
    ↓             as of the 2026-08-09 handoff; that's no longer true.
Writer
    ↓
Critic
    ↓
Human Review

Two things drove this session, in order: the 2026-08-09 handoff's flagged
Scorer-vs-Critic-score ambiguity got resolved (project owner chose "build
the real Scorer now"), and then almost the entire rest of the session
turned out to be debugging why Scorer had nothing to score against —
roughly 40% of all postings had no stored job description at all, for two
completely different root causes across two different ATS adapters. Both
are fixed. The session ends on a NEW, real, still-open request: Scorer
works, but running it against every posting wastes most of its LLM calls
on postings a free keyword/location filter would have already excluded.

⸻

1. What Was Built / Fixed This Session

1a. Scorer agent — src/biohunter/scorer.py (new) + cli.py's
`score-postings` subcommand + config/roles.yaml's `scorer_fit` role
(added by the project owner, not by this session — see section 5 for
what to confirm). One blind LLM judgment call per posting, scoring job-
FIT (role/skill/background alignment, location, seniority) against the
candidate's Qdrant catalog (professional_summary, key_skills,
career_history, education) and config/search_criteria.yaml's stated
preferences — BEFORE any resume draft exists. Writes postings.score /
score_rationale (columns existed since Phase 1, never populated until
now). Deliberately NOT visa/salary-aware — no data source for either
exists anywhere in this codebase; scorer.py's own docstring says so
explicitly rather than faking it.

IMPORTANT CORRECTION LOGGED IN scorer.py's OWN DOCSTRING: the first draft
of this module was written against an AST-outline summary of
selection.py/writer.py/qdrant.py, not their real source, and shipped with
three real bugs that were only caught once the real files were uploaded
and compared line-by-line:
  - Wrong Qdrant section_type values (guessed "summary"/"skills", real
    ones are "professional_summary"/"key_skills") — would have silently
    returned zero catalog entries every run, no error.
  - llm.complete() call omitted `think` entirely — selection.py's own
    docstring says omitting it does NOT behave like think=False, it runs
    4-6x slower like think=True.
  - key_skills payloads have no `label` field (only `text`) — running
    them through load_catalog()/CatalogEntry the same way as the summary
    catalog produced blank labels.
All three are fixed now. The lesson, stated for whoever picks this up:
when a source file isn't in the current session's uploads, treat any
code written against its outline/docstring-only summary as unverified
until the real file shows up — this cost most of a session's worth of
debugging that a real-source read would have prevented up front.

1b. cli.py: `keyword_filter_match()` extracted from `cmd_list_postings`'s
previously-inline substring logic (behavior-preserving refactor).
`DEFAULT_BAY_AREA_LOCATIONS` — which existed as dead code before this
session (defined, never referenced anywhere) — is now actually wired in,
consumed by dashboard.py's "Bay Area only" checkbox. New `score-postings`
subcommand: `--rescore` (widen scope to already-scored postings),
`--limit N`, `--model ROLE=VALUE` (LLMClient override), `--think`. A
scored posting's status moves 'new' -> 'scored'; a plain re-run without
--rescore only ever touches unscored postings.

1c. dashboard.py (built at the very start of this session, before the
description-fetch investigation took over): postings-index filter bar
(keyword/location/Bay-Area-toggle/company/first-seen date range/min fit
score) + pagination (60/page — the prior session's 693-postings-
unpaginated problem) + manual posting entry (GET/POST /postings/manual,
lightweight find-or-create-company-by-name, careers_url stand-in = the
posting's own URL since the column is NOT NULL with no sensible fake to
invent). Fit-score badge (_fit_score_badge, reads postings.score) kept
visually distinct from the existing resume-quality badge (_score_badge,
reads drafts.final_score) — these are two different scores this project
has deliberately kept separate since the 2026-08-09 handoff; the UI now
reflects that on purpose.

1d. schema.sql: comment-only update noting postings.score is now
populated by scorer.py. Also: this session accidentally reintroduced the
project's own known gotcha — a semicolon inside a `--` comment broke
db.py's naive `_split_statements()` (`ValueError: incomplete input`).
Caught and fixed same-session. Worth remembering EVERY time schema.sql
gets a prose comment edited: no semicolons in comment text, ever, until
someone fixes _split_statements() itself to strip comments before
splitting (not done this session — a real, standing fix worth doing
eventually so this class of bug stops being possible).

1e. workday.py — THE BIG FIX. Root cause of most of this session's time:
this adapter's list/search endpoint (`/wday/cxs/{tenant}/{site}/jobs`)
only ever returns title/location/URL. It never fetched a description at
all — not a bug in cleanup, a complete absence of the fetch. Confirmed
via real curl against Amgen and Guardant: a SECOND endpoint,
`/wday/cxs/{tenant}/{site}{external_path}` (mirrors the adapter's own
public-URL construction, just with a `/wday/cxs/{tenant}/{site}` prefix),
returns `jobPostingInfo.jobDescription` as HTML. Added a per-job GET to
that endpoint, with a self-contained 0.3s delay between calls (this
adapter now makes one extra HTTP round trip PER JOB — 429 extra requests
across the 5 companies in this DB alone). Deliberately did NOT thread the
existing RateLimiter through ATSAdapter.fetch_postings()'s signature —
that would touch base.py's abstract method and every other adapter file
for a need that, so far, is Workday-specific. Fails soft per-job (a bad
detail fetch never sinks the rest of that company's Scout pass) and now
logs TWO distinct warning types: an outright request failure, vs. a 200
response that simply has no jobPostingInfo.jobDescription field (the
latter added mid-session specifically because the first version of this
fix was silently returning None with zero log trail for ~25-45% of jobs,
which took real effort to even notice, let alone diagnose).

1f. jobvite.py — SAME SYMPTOM, DIFFERENT MECHANISM, LESS CONFIDENCE. This
adapter has no JSON API at all (official Jobvite API needs a customer
key); it scrapes a plain HTML listing page, which — like Workday's list
endpoint — never contained description text. Added a per-job GET of each
job's own detail page + BeautifulSoup scrape via a guessed selector list
(_DESCRIPTION_SELECTORS: #jv-job-detail-description,
.jv-job-detail-description, div.jv-page-body, article). UNLIKE the
Workday fix, this selector list is NOT confirmed against real Jobvite
HTML — it's a best guess. First real run got BioMarin to 116/153 non-null
descriptions, which is encouraging (mostly working) but not proof the
selector is exactly right for every posting; the remaining 37 nulls could
be selector misses OR the same closing-postings race condition described
in section 2. Worth a real curl-and-view-source check against one real
BioMarin job page next session if anyone wants to tighten this further —
not done this session because the partial success meant it wasn't the
most urgent thread to keep pulling.

⸻

2. Bugs Found and Root-Caused (some real, some false alarms — worth
   keeping both kinds straight)

REAL bugs, fixed this session: schema.sql semicolon (1d); scorer.py's
three signature bugs (1a); workday.py's total absence of description
fetch (1e); jobvite.py's total absence of description fetch (1f).

FALSE ALARM, investigated and closed: Guardant Health showed 0/73
descriptions at one point, looking like a Guardant-specific structural
failure distinct from every other Workday company. Confirmed via curl
against the real detail endpoint that Guardant's response shape is
IDENTICAL to Amgen's — the 0/73 was simply a run captured before the
workday.py fix existed in the working copy at that time. Re-ran after
the fix: 69/87, same range as every other Workday company. Nothing to
fix here; flagging only so nobody re-investigates a closed thread.

FALSE ALARM #2, investigated and closed: after the workday.py fix
landed, Amgen/Genentech/Gilead/Denali/Guardant all showed a persistent
~25-45% partial-fill gap with ZERO logged failures (--debug showed every
detail-fetch request returning 200, but the description was still
missing on plenty of rows). This looked like a silent bug in the fetch
logic. Root-caused instead as a race condition: for a large company
(Genentech: 345 jobs, sequential per-job detail-fetches with a 0.3s
delay = several real minutes of wall-clock time), some postings close or
get pulled between Scout's initial list-call and the per-job detail-call
reaching them later in that same pass. Confirmed by comparing two
consecutive run-scout passes: the SECOND pass's live posting counts per
company matched almost exactly the FIRST pass's description-populated
counts (not total counts) — i.e., the description-less postings weren't
randomly failing, they were closing in real time and then aging out of
the next list-call entirely. A clean re-run with the (by-then-fixed)
warning logging in place showed near-zero failures of either kind. Not a
code bug — an inherent property of a two-step list-then-detail fetch
design against a live, changing job board. Nothing further to build here
unless the gap reappears at a scale that looks abnormal again.

NOT YET INVESTIGATED, still open: companies.ats_type in the DB can go
stale relative to companies.yaml — confirmed for Denali (DB showed blank
ats_type; companies.yaml has ats_type: workday). Root cause:
detector.py's _get_or_create_company_id() only INSERTs a new company
row; it never UPDATEs ats_type/careers_url/etc. on an existing row when
companies.yaml changes later. Cosmetic only — run_scout() itself routes
using the freshly-loaded CompanyConfig from load_companies(), not the DB
column, so Scout behavior is unaffected. Worth a real fix eventually
(have _get_or_create_company_id refresh those columns on every run, not
just insert-if-missing) but low priority since nothing is currently
broken by it — just misleading if someone diagnoses off the DB column
again like this session almost did.

NOT YET INVESTIGATED, still open: Scribe Therapeutics 404s on its
Greenhouse board URL every single run-scout pass
(`https://boards-api.greenhouse.io/v1/boards/scribetherapeutics/jobs`).
Never looked into this session — could be a renamed/deactivated board, a
typo'd ats_slug in companies.yaml, or the company moved off Greenhouse
entirely. Doesn't crash anything (run_scout's per-company try/except
catches it and reports it as an error result, same as designed), just a
standing, unexplained error every run.

⸻

3. Current State

- All 4 real ATS integrations that needed a description fix now have
  one: Greenhouse/Lever/Ashby/Jobsyn already worked before this session;
  Workday and Jobvite are fixed now (Jobvite's fix is functional but
  its CSS selector is unverified — see 1f).
- Description fill rate, last confirmed numbers before this session's
  final clean run (should be re-checked at the START of next session —
  see section 6's first query): Amgen 40/78, Astellas 123/123, BioMarin
  116/153, Denali 17/21, Genentech 250/345, Gilead 40/102, Guardant
  69/87, Mammoth 2/2, Nurix 25/25. A subsequent clean run showed near-
  zero new failures of either logged type, meaning these numbers should
  be close to final/stable now — CONFIRM with a fresh query, don't
  assume.
- score-postings has been run partially against real data (Ctrl-C'd
  mid-Astellas-batch, not a full run). Scores that did complete looked
  qualitatively sound — correctly penalizing commercial/marketing/non-
  scientist roles for a lab-science candidate profile, with sensible
  one-line rationales. No full run against the complete, now-larger
  posting set has happened yet.
- Model for scorer_fit: the project owner added `gemma4:12b-mlz` [sic —
  confirm exact model string] via Ollama, per this session's roles.yaml
  guidance. It was noticeably slow per-posting (multi-second/posting on
  local hardware) and a switch to a smaller model (gemma3:1b-it-qat) was
  discussed as a speed fix, but IT'S NOT CONFIRMED WHETHER THE PROJECT
  OWNER ACTUALLY MADE THAT SWITCH. Check config/roles.yaml's scorer_fit
  entry at the start of next session before assuming which model is
  live.
- Total live posting count across all companies has been climbing
  across runs (936 mentioned by the project owner in their latest
  message — higher than any total this session's queries showed, e.g.
  ~845 summed from the last full company-by-company query). This is
  expected — Scout finds new postings and companies post new reqs
  continuously; it's not evidence of a bug, just confirms this dataset
  keeps growing.

⸻

4. NEXT SESSION: The Actual, Now-Open Request

Project owner's own words, paraphrased faithfully: running score-postings
against every 'new' posting is wasteful, because a huge fraction of
those postings are obviously irrelevant on LOCATION or JOB TYPE alone —
no LLM judgment needed to know a sales/marketing role in Kitchener-
Waterloo isn't a fit for a Bay-Area-focused scientist. Concrete number
given: applying LOCATION filtering alone (the exact logic already built
in keyword_filter_match()/DEFAULT_BAY_AREA_LOCATIONS, already live in the
dashboard's filter bar and cli.py's list-postings) cuts 936 postings down
to 279 — a ~70% reduction. Running Scorer's LLM call against all 936
anyway means ~70% of those calls are pure waste on postings a free,
instant substring filter would have already excluded.

The fix is NOT "make the LLM faster" (a smaller model helps some, but
doesn't address the structural waste — it's still doing ~657 unnecessary
calls, just somewhat quicker per call). The fix is: apply the SAME
already-built keyword_filter_match()/DEFAULT_BAY_AREA_LOCATIONS pre-
filter to the SET OF POSTINGS Scorer considers, BEFORE any LLM call
happens for a posting that the filter would exclude anyway.

Two pieces here, deliberately separated by size/risk — read both before
starting either:

4a. Pre-filter flags on `score-postings` itself (CLI-only, small, no
design-decision baggage, do this FIRST): add --location-include /
--location-exclude / --title-include / --title-exclude / --bay-area
flags to cmd_score_postings, reusing keyword_filter_match() and
DEFAULT_BAY_AREA_LOCATIONS from cli.py EXACTLY the way dashboard.py's
index() route already does (see that route's own "Keyword/location
matching stays in Python, reusing cli.py's exact predicate" comment —
this is the third place this same logic would be reused, which is
exactly the point). Apply the filter to the SQL query's result rows
BEFORE the loop that calls score_posting() — an excluded posting must
cost zero LLM calls, not one. This alone solves the "936 -> should only
score 279" problem outright, today, from the CLI, with no dashboard
changes required. Recommended default even without extra flags: consider
whether score-postings should read config/search_criteria.yaml's
location_include/location_exclude by default (matching cmd_list_postings'
own default-source-of-filters behavior) rather than defaulting to "score
literally everything" — this is a real design choice, not obviously one
way or the other, worth deciding out loud rather than silently picking.

4b. Dashboard-triggered Scout + pre-filtered score run (the "should
allow user to run-scout... in the dashboard" part of the request) —
BIGGER, separate, has a real precedent-reversal decision buried in it:
  - scorer.py's own docstring currently says, on purpose: "like
    run_scout(), this is driven from the CLI... not from the dashboard."
    That was a deliberate scope decision from earlier this session.
    Adding a dashboard "Run Scout" / "Score these postings" button
    REVERSES that decision — name it explicitly when it happens, don't
    let it happen by accident as a side effect of building the button.
  - The mechanism to reuse already exists and is proven: dashboard.py's
    Generate/Regenerate flow already runs a background thread and
    returns a job id immediately, with the browser polling
    /jobs/<job_id>.json until done. A "Run Scout" or "Score filtered
    postings" button should use this SAME pattern, not invent a new one.
  - The dashboard's existing filter bar (built in 1c) is ALREADY the
    right UI surface for "which postings should Scorer touch" — next
    session's actual UI work is wiring a "Score these N filtered
    postings" button that runs Scorer over EXACTLY the currently-active
    filter set (same keyword_filter_match() call dashboard.py's index()
    already makes to render the cards), not building a second, separate
    filter UI for scoring.
  - Say this to the project owner up front, don't let them discover it
    the hard way: even a location-filtered 279 postings, scored
    sequentially against a local Ollama model, is real wall-clock time
    (minutes, not seconds). A background-job UI for this NEEDS a
    progress indicator (e.g. "furled 43 of 279") — a bare spinner will
    look identical whether it's working or hung, and that's a bad
    experience for a job that can legitimately take several minutes.

Build 4a first. It's small, immediately useful, and doesn't require
deciding whether Scout/Scorer become dashboard-triggerable. Don't let
4b's bigger scope block 4a's five-minute win.

⸻

5. Open Items to Confirm at the Start of Next Session (don't assume,
   check)

- Re-run the description-fill-rate query
  (`SELECT companies.name, COUNT(*), COUNT(postings.description) FROM
  postings JOIN companies ON postings.company_id=companies.id GROUP BY
  companies.name;`) to get final, post-fix numbers — last session ended
  before this was re-confirmed.
- Check config/roles.yaml's actual current scorer_fit model — gemma4:
  12b-mlx (slow, confirmed working) vs. a possible switch to gemma3:
  1b-it-qat (fast, untested for output-format reliability at scale) was
  left unresolved.
- config/search_criteria.yaml's REAL content was never uploaded or seen
  this entire session — everything about location_include/exclude and
  title_include/exclude was inferred from config.py's SearchCriteria
  dataclass shape only, never the actual file. Get it uploaded next
  session, especially before deciding 4a's "should score-postings
  default to search_criteria.yaml's filters" question.
- jobvite.py's _DESCRIPTION_SELECTORS is unverified — works well enough
  in practice (116/153) but hasn't been confirmed against real Jobvite
  HTML the way workday.py's endpoint shape was confirmed via curl.
- Scribe Therapeutics's Greenhouse 404 has never been looked into.
- companies.ats_type staleness in the DB (Denali example) is a known,
  low-priority, unfixed gap in detector.py's _get_or_create_company_id().

⸻

6. Recommended Files to Upload (next session)

Core (touched or directly relevant this session):
src/biohunter/cli.py              (keyword_filter_match, score-postings,
                                    DEFAULT_BAY_AREA_LOCATIONS — build 4a
                                    directly on top of this file)
src/biohunter/dashboard.py        (filter bar UI + background-job
                                    pattern from Generate/Regenerate —
                                    both needed for 4b)
src/biohunter/scorer.py           (this session, new)
src/biohunter/ats/workday.py      (this session, fixed — reference only
                                    unless the description-fetch thread
                                    reopens)
src/biohunter/ats/jobvite.py      (this session, fixed but selector
                                    unverified — bring if tightening it)
config/roles.yaml                 (NEEDED — confirm scorer_fit's actual
                                    live model before assuming)
config/search_criteria.yaml       (NEEDED, never uploaded this session —
                                    real location/title preferences,
                                    directly relevant to 4a's default-
                                    filter design question)
schema.sql                        (reference — postings.score/
                                    score_rationale, drafts.final_score)

Reference:
2026-08-09 handoff (prior session — dashboard/filtering/manual-add
  context, and the original Scorer-vs-Critic-score framing this
  session resolved)
this file

⸻

Working Style

Continue the mentoring style used throughout this project — same
standing rules, plus one this session earned the hard way:

* Explain rationale before coding.
* Check for existing logic before building new logic — this session's
  keyword_filter_match() extraction and reuse (three separate places
  now: cli.py, dashboard.py, and 4a's planned score-postings flags) is
  the same principle applied a third time.
* Avoid unnecessary abstraction.
* Favor incremental, testable milestones.
* If a proposed change would intentionally diverge from prior behavior
  (e.g. 4b reversing "Scout/Scorer are CLI-only"), say so explicitly.
* No auto-submit / no auto-send — human approval remains the final step.
* NEW, learned this session: when a source file a new module depends on
  (Qdrant payload shapes, an LLM client's exact call signature, another
  module's constants) is NOT in the current session's uploads, treat any
  code written against a summary/outline of it as unverified until the
  real file is seen. This session's scorer.py shipped three real bugs
  from exactly this gap, and root-causing them (plus the description-
  fetch investigation they were tangled up with) consumed most of a
  session that could have been spent on the pre-filtering feature
  instead. Ask for the real file before writing code against its
  assumed shape, not after.
