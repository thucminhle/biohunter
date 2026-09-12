# BioHunter handoff — Writer subsystem step 6 (humanizer) closed

**Read this file first**, per this project's own norm, before touching
`dashboard.py` or any related file. Then pull whatever current files you
need directly from GitHub (see "Access" below) rather than asking the
user to upload them.

## Access

- Repo: `thucminhle/biohunter`, default branch `main`. GitHub read/write
  via Composio, connected to the user's account (`thucminhle`).
- **Write workflow: commit to a feature branch and open a PR for the
  user to review and merge themselves. Never commit straight to `main`.**
  This applies to code AND docs (this handoff doc itself was written
  this way).
- Real file layout is under `src/biohunter/` (`dashboard.py`, `db.py`,
  `drafts_db.py`, `writer.py`, `diff.py`, `humanizer.py`,
  `resume_pdf.py`, etc.), not repo root. `schema.sql` and `docs/` are
  at repo root.

## Hard guardrails (carried through the whole project)

- **No auto-submit / no auto-send, anywhere.** Filler and Networker
  (not yet built) must always stop at a human-approval gate before
  anything goes out.
- **schema.sql pre-flight check, mandatory before touching schema.sql
  specifically:** `db.py`'s `init_schema()` does a naive
  `.split(';')` to run statements. A semicolon anywhere inside a `--`
  comment breaks it -- this has bitten the project 3 times
  (2026-08-23, 2026-08-24, and caught pre-emptively 2026-09-07).
  Testing "does it execute in sqlite3" does NOT catch this (stdlib
  sqlite3 tolerates a stray comment-only fragment as a no-op;
  `libsql_experimental`, what this project actually runs against,
  does not). Before handing back any schema.sql edit, explicitly grep
  every comment line for a stray `;`, or simulate the naive
  `.split(';')` and check for comment-only fragments -- don't just
  syntax-check. **Not touched this session -- carried forward
  unchanged.**
- **New, from this session: a merged PR is done.** Once the user
  clicks Merge on a PR, any further commits pushed to that same
  branch do NOT retroactively join `main` -- they're stranded until a
  fresh PR is opened for just the remaining commits. This actually
  happened this session (PR #3 was merged mid-phase, before Phase D's
  commit landed on the branch; PR #4 was a follow-up just for that
  one stranded commit). When committing across multiple phases to one
  branch, say explicitly "ready to merge" only once nothing more is
  coming, rather than letting the user merge opportunistically
  whenever the PR looks green.
- **New, from this session: commits made via the GitHub API bypass
  local pre-commit hooks.** This project's `.pre-commit-config.yaml`
  has a local hook (`update-file-tree`, running
  `./scripts/run_hooks.sh`) that regenerates `docs/AST_OUTLINE.md` and
  `docs/FILE_TREE.txt` on every local `git commit`. API-based commits
  never trigger it, so those two files silently go stale after a
  session that commits via the API across several phases. Run
  `./scripts/run_hooks.sh` locally and commit whatever it regenerates
  once a multi-phase branch is otherwise done, don't assume it's
  automatic.
- **New, from this session: any local-model call reachable from a
  Flask route needs the async job-queue pattern, not a synchronous
  call inside the request.** This was already true for `/generate`
  (`_run_generation()`, persisted job queue, polling progress bar --
  see Captain's status below) but the humanizer was first built
  synchronously anyway, because a small synthetic smoke test (a
  3-bullet sample) completed fast enough to look fine. Against real
  resume-length content it hit a genuine 300s read timeout. A smoke
  test passing is NOT the same as the architecture being validated --
  test any new local-model route against real content size, not just
  a toy input, before considering it done.
- **New, from this session: every Ollama-backed role's call site must
  pass `think` explicitly** (`True` or `False`), never leave it
  unset. `OllamaNativeClient.chat()`'s own docstring already noted
  other callers (`selection.py`/`writer.py`) do this deliberately;
  `humanizer.py`'s first version didn't, and that was likely the
  dominant cause of the 300s timeout above (confirmed via a direct
  `curl` timing test against Ollama's native API with `think: false`
  -- healthy ~26 tok/s, no sign of runaway reasoning). Silent
  default-on thinking mode doesn't error, it just gets slow, so it's
  easy to miss.

## Working style

- Mentorship, not just finished code: walk through development and
  testing step by step.
- Low-level/teachable code: write it out and have the user type/apply
  it themselves, with an exact anchor line (never a vague "add this
  near X" -- a vague anchor once broke a whole dashboard app).
- Heavier implementation: fine for Claude to write directly, but
  explain what it does. When editing an existing multi-thousand-line
  file programmatically (this session's `dashboard.py` refactor),
  `ast.parse()` each intermediate edit before applying the next one --
  don't wait until the end to discover a broken anchor or an
  accidental brace-collapse from `str.format()` on a string containing
  literal `{{`/`}}` (this bit the async refactor once this session;
  plain concatenation is the safer choice once double-braces are
  involved).
- Click-test live before moving to the next step, even when a code
  review says the logic is correct -- "reads correctly" isn't the
  same as "renders correctly," and this project treats live
  confirmation as the actual bar, not a formality. This session's
  humanizer went through three live-test rounds (synchronous version
  timing out, async version still timing out on the real root cause,
  final version confirmed end-to-end on real content) before being
  called done.

## Status: Captain -- fully closed

All 5 items (persisted job queue, multi-select batch generation,
unified progress-bar contract, combined scout+check job, permanent
job-history page) confirmed done via code + live click-through.
Unchanged this session, but its `_run_generation()` /
`_job_display()` / `_job_progress_fraction()` / `job_status_page()`
patterns were the direct template the humanizer's async fix (below)
was built from.

## Status: Writer subsystem -- 5 of 6 steps done, confirmed live

Build order note: the original plan was steps 1 through 6 in order.
This session deliberately did step 6 before step 5, per explicit user
direction ("I want to jump to step 6... Step 5 can be addressed
another time"). Step 5 (DOCX export) is unchanged and still open.

- [x] Step 1 -- in-dashboard editor. Confirmed live 2026-08-24.
- [x] Step 2 -- Preview + PDF export both read from `final_edit`.
      Confirmed live 2026-09-07.
- [x] Step 3 -- regenerate-while-editing archiving. Confirmed live
      2026-08-24.
- [x] Step 4 -- version history panel. Built as PR #1, merged
      2026-09-08, confirmed live.
- [x] **Step 6 -- local-LLM humanizer, refined from "proofreader"
      this session.** Confirmed live 2026-09-11. Full detail below.
- [ ] Step 5 -- DOCX export. Not started. Spec unchanged from the
      previous handoff -- see "Next up" below.

### Step 6 detail -- what shipped and why

**The reframe.** The original spec (previous handoff) was a plain
grammar/phrasing proofreader. The user wanted it to actively humanize
the writing instead -- reduce AI-generated rhythm/phrasing tells
(repetitive bullet openers, uniform sentence length, empty inflated
modifiers like "dynamic"/"results-driven" with no metric attached,
mirrored clause structure) while staying formal and positive, because
the output still has to score well with ATS parsers and read well to
a recruiter. The key tension named and resolved: "humanize" pulls
toward paraphrasing, but ATS/recruiter scoring rewards exact-term
overlap with the job description -- so the system prompt hard-rules
against paraphrasing any term that appears in the JD, passing the
full JD text as reference context rather than building a separate
keyword-extraction step.

**Files:**
- `config/roles.yaml` -- new `writer_humanizer` role
  (ollama/gemma4:12b-mlx, same model as `writer_selection`/
  `critic_review`).
- `src/biohunter/diff.py` -- new `WordDiffHunk` dataclass,
  `word_diff_hunks()`, `apply_word_diff_hunks()`, additive alongside
  the existing `_word_diff_ops` (Revision History's own diff path is
  untouched). A hunk keeps a `replace` as one unit (never split into
  a separate delete+insert) so a checkbox always means something
  coherent to accept or reject.
- `src/biohunter/humanizer.py` (new file) -- `humanize_section(text,
  section_key, job_description, llm, *, role="writer_humanizer",
  timeout=600)`. Per-section instruction text, strictest on
  `tailored_bullets` (only vary the leading verb/connective words,
  never touch a noun phrase). Persistence-agnostic and UI-agnostic
  like `diff.py`/`critic.py` -- takes text in, returns proposed text
  out.
- `src/biohunter/dashboard.py` -- `humanize_propose()` (job starter),
  `_run_humanize()` (background worker, one step per section),
  `humanize_review(job_id)` (GET route, renders the accept/reject
  page from the finished job's stored fields), `humanize_apply()`
  (reconstructs each section from checked hunks, writes to
  `final_edit` -- the only write in the whole flow), plus `'humanize'`
  branches in `_job_progress_fraction()` / `_job_display()` /
  `job_status_page()`'s polling JS, and a "Humanize (review
  suggestions)" button in the editor panel.
- No new schema.sql table. Rejected suggestions are never persisted
  -- same scope decision step 4's version history already made for
  proofreader/humanizer suggestions, reconfirmed here.

**Design decisions the user made explicitly (asked via elicitation,
not assumed):**
- Runs on **all three** sections (summary/bullets/cover letter), not
  just prose.
- Model: reuse `gemma4:12b-mlx` (already proven for this project's
  other Ollama roles), not a different one.
- Accept/reject granularity: **per individual change** (word-diff
  hunk), not per whole section.

**What went wrong before it worked, in order (all fixed, all on
`main` now):**
1. PR #3 merged mid-phase (before Phase D's commit landed on the
   branch) -- see the new guardrail above. Fixed by PR #4 (the one
   stranded commit).
2. First live click-test: `HTTPConnectionPool ... Read timed out
   (read timeout=300)` against real posting content -- the earlier
   synthetic 3-bullet smoke test was too small to expose this. Fixed
   by PR #5: moved to the async job-queue pattern (background thread +
   polling), matching Captain's `_run_generation()` exactly rather
   than inventing something new. This fixed the *symptom* (blocked
   request) but the underlying call was still genuinely slow.
3. Second live click-test, now via the progress bar: still timed out
   at 300s on "Humanizing tailored bullets," just without crashing the
   page this time. Root-caused to `think` never being passed
   explicitly. Fixed by PR #6: `think=False` + 600s per-call timeout,
   both scoped to `humanize_section()`'s own call, no changes to
   `llm.py`'s global defaults or any other role.
4. Confirmed via a direct `curl` timing test against Ollama's native
   `/api/chat` with `think: false`: 239 tokens in 9.04s, ~26 tok/s --
   healthy, normal generation speed, no sign of runaway reasoning.
5. Third live click-test, full flow: propose -> progress bar (visible
   per-section step counter) -> review page (word-level diff hunks,
   del/ins styling) -> partial accept/reject on real content -> Apply
   -> confirmed the accepted changes landed in the editor panel and
   the rejected ones didn't. Discard-all path also click-tested.
   **This is the version currently on `main`.**

## Next up: step 5 (DOCX export)

Unchanged from the previous handoff -- nothing about this was touched
this session:

- `resume_docx.py`, mirroring `resume_pdf.py`'s structure -- reuse
  `report.py`'s shared markdown-parsing helpers
  (`_split_headed_sections`, `_render_prose_block`), swap the
  rendering backend from HTML+Playwright to `python-docx`. New
  dependency: `pip install python-docx`.
- Two new routes, `posting_resume_docx` / `posting_cover_letter_docx`,
  mirroring the existing PDF routes -- almost certainly should also
  read from `_display_draft()` / `final_edit`, same as the PDF routes
  do, for consistency.
- Candidate signature image: new `candidate_settings.signature_path`
  field, uploaded via Settings, embedded in both PDF and DOCX cover
  letters between "Sincerely," and the typed name. Not yet scoped in
  detail -- confirm with the user whether this ships alongside DOCX
  export or separately.
- **Still true from the previous handoff: `AST_OUTLINE.md` should be
  read before starting DOCX export**, in case it documents
  resume-structure assumptions `resume_docx.py` needs to match. (This
  session did touch `AST_OUTLINE.md` -- see the pre-commit-hook
  guardrail above -- but only to keep it in sync, never actually read
  its contents for design purposes.)

## Loose end, not blocking

Candidate signature image (see step 5 above) is still unscoped detail
-- worth a quick confirm-with-user pass before writing any code for
it, rather than guessing the field name/UI. Carried forward unchanged
from the previous handoff; still open.
