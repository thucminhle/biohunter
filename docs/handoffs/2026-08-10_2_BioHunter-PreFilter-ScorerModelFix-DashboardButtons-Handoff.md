# BioHunter — Pre-Filter Completion, Scorer Model Fix, Dashboard Scout/Score Buttons

**Session date:** 2026-08-10 (second session this date — continuation of
`2026-08-10_BioHunter-Scorer-DescriptionFetch-PreFilter-Handoff.md`, which
this doc supersedes as the "read first" pointer).

**One-line summary:** Both halves of that handoff's ask are built (4a
pre-filter flags, 4b dashboard buttons), plus a real bug found and fixed
along the way (scorer_fit's model was silently non-compliant with the
required output format). **The dashboard changes (4b) have NOT been run
in a real browser yet** — only Python-syntax-checked. That's the most
important thing to do first next session, not assume-and-move-on.

---

## 1. What shipped, in order

**4a — `score-postings` pre-filter (`src/biohunter/cli.py`):** Added
`--location-include` / `--location-exclude` / `--title-include` /
`--title-exclude` / `--bay-area` flags to `cmd_score_postings`, reusing
`keyword_filter_match()` / `DEFAULT_BAY_AREA_LOCATIONS` exactly as
`cmd_list_postings` and `dashboard.py`'s `index()` already did — no new
filter logic. Filtering happens on the SQL rows *before* any LLM call, so
an excluded posting costs zero calls, not one. Defaults to reading
`config/search_criteria.yaml`'s filters (matching `cmd_list_postings`'
own default-source-of-filters behavior) rather than scoring everything
by default — this was the open design question from the prior handoff,
now resolved in favor of "on by default." Also fixed a message bug
where the printed summary conflated pre-`--limit` and post-`--limit`
counts.

**Real numbers confirmed this session** (re-run, not assumed):
description-fill rate is stable at **682/936 postings (73%)** across two
consecutive sessions — see per-company breakdown below. With the real
`search_criteria.yaml` filters applied (7 Bay Area location strings +
"remote"; postdoc/intern title excludes; no title-include restriction),
**254 of 936 postings pass the title/location filter**, and of those,
**192 have a stored description and were actually scored; 62 don't and
were skipped** — that 62/254 gap is entirely the known, pre-existing
description-fetch gap (Workday/Jobvite), not anything new.

```
Amgen|78|40   Astellas|123|123   BioMarin Pharmaceutical|153|116
Denali Therapeutics|21|17   Genentech|345|250   Gilead Sciences|102|40
Guardant Health|87|69   Mammoth Biosciences|2|2   Nurix Therapeutics|25|25
```

**Real bug found and fixed — `scorer_fit`'s model (`config/roles.yaml`):**
End-to-end testing of the pre-filtered path (not just "does it run
without crashing," but "does it produce a parseable score") surfaced
that `gemma3:1b-it-qat` (the model `scorer_fit` was pointed at) was
silently non-compliant with the required "paragraph + `SCORE: <n> --
<rationale>`" format. Its entire response, confirmed via a temporary
debug log added to `scorer.py`, was the literal 9 characters
`"SCORE: 6\n"` — no paragraph, no rationale, not even the dash separator
`parse_score()` requires. Not a truncation or parsing bug; the model
simply didn't attempt the instructed format. **Fixed** by switching
`scorer_fit` to `gemma4:12b-mlx` (this project's proven quality-tier
model, already reliable elsewhere in this codebase) — the project
owner's explicit choice over `qwen2.5:14b` after being given the real
tradeoff (proven-but-slower vs. fast-but-untested-on-this-format).
Re-tested after the switch: clean parses, sound and well-differentiated
rationales (e.g. correctly scored a corporate L&D role 3/10 against a
lab-science PhD background, correctly scored a clerical role 1/10 for
seniority mismatch while separately noting its location *did* match —
i.e. reasoning about the two dimensions independently, not collapsing
them). Full 254-posting filtered run subsequently completed: **192
scored, 62 skipped (no description), 254 considered.**

**`scorer.py` cleanup:** kept the diagnostic `logger.debug(response.text)`
line added during the bug hunt (useful going forward, matches
`selection.py`'s own convention, costs nothing without `--debug`).
Replaced the docstring's stale "no `scorer_fit` entry exists yet, suggest
adding `qwen2.5:14b`" section (written before `scorer_fit` existed) with
an accurate account of what actually happened and why.

**One thing left genuinely unresolved, not silently dropped:** a scored
posting (Guardant Health, "Sr. Client Services Specialist") got a 1/10
with a rationale claiming it *"fails to meet your location
preferences"* — but that posting only got scored because it *passed*
the location filter. This could be the LLM correctly catching a nuance
a substring filter can't (e.g. a location string that matches "remote"
but actually excludes CA), or it could be the model reasoning
incorrectly about a dimension it shouldn't weigh that way. **Never
checked** — the project owner chose to move on to 4b instead. Worth a
quick look before trusting location-reasoning across all 192 rationales
at scale.

**4b — Dashboard Scout/Score buttons (`src/biohunter/dashboard.py`):**
Explicitly reverses `scorer.py`'s own prior "CLI-only" decision (named
in the module docstring, not left implicit). Reuses the exact
Generate/Regenerate background-job mechanism (`_jobs`/`_set_job`/
`_get_job`, a daemon thread, `/jobs/<job_id>.json` polling) — the job
dict now carries a `kind` field (`"generate" | "score_batch" | "scout"`)
so the polling page shows the right progress shape for each:

- **"Score filtered postings" button** — appears on the postings index,
  next to the filter bar, showing a live count of the currently-matched
  set. POSTs the current filter state (hidden fields, exact mirror of
  the filter bar's GET params) to `POST /postings/score-batch`, which
  re-derives the filtered set server-side via a new shared
  `_filtered_postings()` helper (extracted from `index()`'s own query +
  `keyword_filter_match()` logic — one implementation, two callers, not
  a second filter path) rather than trusting a posting-id list from the
  client. Has a "rescore" checkbox mirroring the CLI's `--rescore` flag.
  Progress is **real**: the job dict tracks `scored`/`skipped`/`total`/
  `current`, updated per-posting by `_run_score_batch()`, which mirrors
  `cmd_score_postings`'s exact DB-write pattern (same UPDATE statement,
  same status-transition logic, same "still writes NULL for an
  unparseable result" behavior) rather than a divergent one.
- **"Run Scout" button** — same job mechanism, calls `run_scout()`
  directly (the same function `cmd_run_scout` calls) and logs to
  `run_log` via `cli.py`'s own `_log_run()` (imported, not duplicated).
  **Its progress indicator is deliberately honest, not fabricated**:
  `src/biohunter/scout/` (wherever `run_scout()`'s real implementation
  lives) was **not** part of this session's uploads, so whether it
  reports progress incrementally as it checks each company is
  unverified. The button shows "running, checking career pages, no
  fine-grained progress available" until done, then a real summary
  (companies checked / new postings / errors) once `run_scout()`
  returns. Wiring real per-company progress through is a small
  follow-up once that module is actually seen — not attempted blind.

**NOT YET DONE:** actually launching `python -m biohunter.dashboard` and
clicking through both buttons in a browser. Everything above was
verified by Python syntax check (`py_compile`) and AST inspection only —
that confirms the code doesn't have syntax errors, not that Flask routes
correctly, that the job-status page's JS renders as intended, that the
CSS layout change (see below) looks right, or that a real Ollama call
inside a background thread actually completes and updates the DB as
expected. Treat 4b as "written, not confirmed" until a real run happens.

**Also touched, worth knowing:** `.detail-header`'s CSS was changed from
block to `flex` (so the new "Run Scout" button sits next to the
"Postings" heading instead of stacking). That class is shared with the
posting-detail page's header — should still stack correctly there (the
`.sub` paragraph is forced to `width: 100%` to force a wrap), but this
is a shared style change and was never actually viewed in a browser.

---

## 2. Files touched this session (full current state, not incremental)

- `src/biohunter/cli.py` — 4a's filter flags on `score-postings`,
  message-format fix, updated module usage docstring.
- `src/biohunter/scorer.py` — debug logging line, docstring cleanup
  (stale `scorer_fit`-doesn't-exist-yet section replaced).
- `config/roles.yaml` — `scorer_fit` switched from `gemma3:1b-it-qat` to
  `gemma4:12b-mlx`, comment rewritten with the real tested reason.
- `src/biohunter/dashboard.py` — 4b in full: new imports
  (`load_search_criteria`, `score_posting`, `run_scout`, `_log_run`,
  `json`), `_filtered_postings()` extracted, `_run_score_batch()` and
  `_run_scout_job()` background functions, `POST /scout/run` and
  `POST /postings/score-batch` routes, `_score_batch_form_html()`
  helper, `job_status_page`'s JS rewritten with `kind`-based branching,
  `.detail-header`/`.score-batch-bar`/`.inline-form` CSS additions.

No files were added or removed — `docs/FILE_TREE.txt` does **not** need
regenerating this time, only the ones above need re-copying into the
repo. All four were sent as complete-file syncs (not patches), per
standing preference — `git diff` right after applying each is still the
right move to confirm nothing landed partially.

---

## 3. Open items to confirm at the start of next session (don't assume)

- **Run the dashboard for real.** `python -m biohunter.dashboard`
  (defaults to port 5050; `--debug` for verbose logs). Click "Run Scout"
  and "Score filtered postings" for real, watch the job-status page
  update, confirm the redirect/summary on completion, confirm the DB
  actually got written to (spot-check `postings.score`/`status` after a
  score-batch run the same way this session spot-checked CLI runs).
- **The Guardant Health location-rationale question above** — never
  checked, worth 30 seconds before trusting rationale text at scale.
- **`scout/__init__.py` (or wherever `run_scout()` lives)** — still
  never uploaded across two sessions now. Needed before Scout's
  dashboard button can get real progress, and generally overdue given
  how many other modules got root-caused this way after being written
  blind against a summary.
- **`roles.yaml`'s `critic_review` comment says "Routed to Anthropic"**
  but its actual config is `provider: ollama, model: gemma4:12b-mlx` —
  same class of stale-comment drift as `scorer_fit`'s own, just not
  fixed yet. Low priority, but now flagged twice.
- Carried forward, still unresolved, still low priority:
  `jobvite.py`'s `_DESCRIPTION_SELECTORS` unverified against real
  Jobvite HTML (works 116/153 in practice); Scribe Therapeutics's
  Greenhouse 404 never investigated; `companies.ats_type` staleness in
  the DB (Denali example) unfixed in `detector.py`.

---

## 4. Recommended files to upload next session

Core (touched this session, needed to continue from current state):
```
src/biohunter/dashboard.py     (this session, needs real browser testing)
src/biohunter/cli.py           (4a, reference for _run_score_batch's mirrored write logic)
src/biohunter/scorer.py        (debug logging kept, docstring updated)
config/roles.yaml              (scorer_fit resolved to gemma4:12b-mlx)
```
Needed, never yet seen (blocking real Scout-progress work):
```
src/biohunter/scout/__init__.py  (or wherever run_scout() is actually defined)
src/biohunter/scout/scraper.py   (if run_scout() delegates per-company work here)
```
Reference:
```
this file
2026-08-10_BioHunter-Scorer-DescriptionFetch-PreFilter-Handoff.md (prior session, still has useful background)
```

---

## 5. Working Style

Same standing rules as always (explain rationale before coding; check
for existing logic before building new; avoid unnecessary abstraction;
favor incremental testable milestones; name a scope/behavior reversal
explicitly when it happens; no auto-submit/no auto-send). Two lessons
this session reinforced, worth carrying forward hard:

- **Verify actual config/model state via real output before trusting a
  docstring's account of it.** This session's real bug (scorer_fit's
  silent format non-compliance) was invisible from source code alone —
  `parse_score()` only logged a warning, never the text that failed.
  `--debug` didn't help until a scorer.py-specific debug line was added.
  The lesson: when something "should" work per the code but doesn't,
  the fix is to look at the actual raw data (raw LLM response, actual
  file content, actual query result), not to reason harder about the
  code in the abstract.
- **A file that passes `py_compile`/AST parsing is not a file that's
  been tested.** 4b is real, substantial, untested code. Don't let it
  get treated as "done" just because it's syntactically valid — the
  first thing next session should do is run it for real, the same way
  this session insisted on real `--debug` runs before trusting the
  Scorer pipeline.
