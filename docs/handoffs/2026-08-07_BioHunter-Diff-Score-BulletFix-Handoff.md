BioHunter — Resume Diff, Display-Only ATS Score, Bullet-Omission Fix (2026-08-07)

Project Summary

BioHunter is a self-hosted, local-first AI platform that automates biotech
job searching and application preparation.

Pipeline:

Scout
    ↓
Scorer
    ↓
Writer
    ↓
Critic
    ↓
Human Review

Phase 1 (native Writer port) and Phase 2 items #1–#2 (Critic + Revision
Loop) were handed off in 2026-08-06_BioHunter-Phase-2-Development.md and
2026-08-07_BioHunter-Critic-Revision-Loop-Handoff.md respectively. That
second handoff also flagged a residual, unresolved data-quality bug (a
Professional Experience heading occasionally coming back with zero
bullets despite catalog bullets being available) as the FIRST thing to
verify before building further on top of Writer. This handoff covers
three things built and validated this session, in the order they were
tackled:

1. Resume Diff (Phase 2 item #1's data-plumbing prerequisite)
2. Display-only ATS Score on Critic's output
3. Root-cause + fix for the residual zero-bullet-heading bug

All three are DONE, wired end-to-end, and validated against real
`verify-revision` runs (Guardant Health, Senior Scientist Mass Spec
posting) with --debug on, not just unit-tested in isolation.

Also worth restating up front, since it changes how much weight to put
on every quality judgment in this session's output: the project owner
does not currently have Anthropic API access (free-tier account only),
so every role in config/roles.yaml — including critic_review and
writer_coverletter, both of which were deliberately routed to Anthropic
in prior sessions for quality-sensitive work — is temporarily pointed
at local Ollama (gemma4:12b-mlx) instead. Critique quality has still
been consistently sharp and well-structured in this session's real
runs, but treat that as a separate open variable, not a fixed baseline,
until Anthropic access is restored and roles.yaml is switched back.

⸻

1. Resume Diff

Status: Built and validated.

Implemented:

* src/biohunter/diff.py (new) — diff_drafts(prev, curr, from_label,
  to_label) diffs any two WriterDraft objects section-by-section
  (tailored_summary / tailored_bullets / cover_letter), returning a
  list[SectionDiff] (section, changed: bool, diff_text: str). Uses
  stdlib difflib.unified_diff — no new dependency.
  diff_revision_result(result: RevisionResult) walks
  RevisionResult.rounds and diffs every consecutive pair, returning
  list[RoundDiff].
* Deliberately reports unchanged sections explicitly (changed=False,
  empty diff_text) rather than omitting them — the project already got
  burned once (Critic/Revision session) by a branch silently no-op'ing
  and looking indistinguishable from "revision happened." A diff step
  that quietly skips unchanged sections would hide that same failure
  mode instead of surfacing it.
* Pure functions, no persistence — same DB/UI-agnostic pattern as
  critic.py/revision.py. Takes data, returns data.
* cli.py: new --show-diff flag on verify-revision. After the existing
  full round-by-round printout, prints a unified diff per section per
  round transition; unchanged sections print "(unchanged)" explicitly.

Validated against a real 2-round Guardant Health run: correctly showed
bullet swaps (e.g. "Documented analytical edge cases..." replaced by
"Performed routine instrument maintenance...") and cover-letter
paragraph reordering between rounds. Also directly surfaced the
zero-bullet-heading bug (see item 3) as a block of `-` lines with no
`+` counterpart under the affected heading — this diff was what turned
"resume looks different" into "here's exactly what disappeared,"
motivating the fix below.

⸻

2. Display-Only ATS Score

Status: Built and validated. Explicitly NOT wired into any stopping
logic — this was a deliberate scope decision, not an oversight (see
"Scope decision" below).

Implemented:

* src/biohunter/critic.py — CRITIC_INSTRUCTION gained a 7th fixed
  header, "## Score", asking for a single strict-format line:
  `SCORE: <integer 1-10> -- <one-sentence rationale>`. critique_draft()
  itself is UNCHANGED — still returns the same freeform str it always
  has. Zero change for any existing caller (revision.py, both CLI
  commands) that just prints or stores that text.
* New parse_score(critique_text: str) -> ScoreResult (score: int|None,
  rationale: str|None) — a separate pure function, not a change to
  critique_draft()'s return type. Regex-based (_SCORE_LINE_RE),
  tolerant of -, --, and em/en-dash variants, since this project's own
  critique output has already been observed drifting on header format
  round-to-round (see the 2026-08-07 Critic/Revision handoff). Never
  raises: no parseable line -> ScoreResult(None, None) + a logged
  warning, same "degrade, don't crash" pattern as
  selection.py's parse_json_response.
* cli.py: both verify-critic and verify-revision now print
  "Score: N/10 -- rationale" (or an "unavailable" message) right after
  each critique's full text.

Scope decision (worth restating for the next session, since the
question "should this gate the revision loop?" will likely come up
again): explicitly decided NOT to build auto-stop-on-plateau/max-score
logic this session. Reasoning discussed and agreed with the project
owner:
  - The score is an LLM's holistic judgment compressed to a number, not
    a real ATS's mechanical keyword-match algorithm — useful, but it
    inherits the same drift/reliability issues as the critique text
    it's derived from.
  - A stopping loop needs the score reliably parseable every round
    first (now true, given json_mode precedent from the Critic/Revision
    session) — but reliably parseable isn't the same as reliably
    meaningful round-to-round.
  - LLM-judged scores are not guaranteed monotonic — "plateau or max"
    is ambiguous on a small integer scale and could stop a loop after
    round 1 by luck, or run indefinitely chasing noise.
  - It would be a real behavior change to run_revision_loop()'s current
    legible contract (always runs exactly revision_rounds), not a
    refinement — flagging explicitly per the project's own working
    style rather than folding it in quietly.
  - Recommended path if/when this gets revisited: watch the score
    behave across several more real postings first, THEN consider an
    opt-in --stop-on-plateau bounded by a hard max-rounds ceiling —
    never a truly open-ended loop.

Validated against the real Guardant Health run: round 0 scored 6/10,
round 1 scored 8/10, both with substantive rationales tied to specific
JD-keyword gaps (PRM, lipids, CLIA/FDA). Parsing worked cleanly both
rounds despite gemma4:12b-mlx's known header drift on the other six
sections.

⸻

3. Bullet-Omission Bug — ROOT CAUSE FOUND AND FIXED

Status: Fixed and validated as resolved against the exact posting that
originally surfaced it.

Background (from the 2026-08-07 Critic/Revision handoff): a Professional
Experience heading would occasionally come back with 0 bullets despite
catalog bullets being available, omitting the heading from the resume
entirely. Two theories going in: (a) a heading-string mismatch in
select_bullets()'s dict lookup (punctuation/whitespace differences), or
(b) a genuine model relevance judgment.

Diagnosis process (this matters for the next session's own debugging,
not just this bug):
  1. First pass: added split logging in selection.py's select_bullets()
     to distinguish "heading key entirely absent from the model's JSON"
     vs. "heading key present but model selected 0 bullets" — these had
     been logging as one identical, ambiguous warning.
  2. Ran --debug against the real Guardant Health posting. Raw JSON
     showed heading pass 1 (select_headings) returning the affected
     headings with byte-identical strings to the catalog — ruling out
     theory (a), the punctuation-mismatch guess, completely. Bullet
     pass 2's JSON object then simply never included keys for two of
     the four selected headings at all (not empty arrays — absent
     keys), consistently the 3rd/4th (last two) of four headings, in
     both rounds.
  3. Root cause identified: BULLET_INSTRUCTION said "You do not need to
     select from every heading" but never specified HOW to skip one —
     the model was interpreting "skip" as "omit the JSON key entirely"
     rather than "include the key with an empty array."

Fix (src/biohunter/selection.py):
  * BULLET_INSTRUCTION now explicitly requires every selected heading
    to appear as a key in the response, with an empty array as the
    valid way to signal "nothing relevant here." ("Never omit a
    heading's key entirely.")
  * The JSON-shape example in the prompt itself was updated to show an
    empty-array case alongside a populated one, reinforcing the rule
    where the model actually reads it.
  * select_bullets()'s warning logic was corrected: the
    "heading-string-mismatch" guess in the warning text was REMOVED
    (proven wrong by the --debug evidence) and replaced with what was
    actually learned, plus a concrete next step (split into one LLM
    call per heading) if the fix doesn't hold on some future posting.
  * No change to the actual selection/validation logic — this is a
    prompt-only fix. The exact-match verbatim-catalog guarantee is
    untouched.

Validated: re-ran the identical Guardant Health command with --debug.
Round 0: the previously-failing heading was selected AND populated with
2 real catalog bullets, no warning fired. Round 1: a different 4th
heading was chosen (normal stochastic heading selection, unrelated),
and the model returned `"Biomarker Strategy & Translation": []` —
an EXPLICIT empty array with the key present, which is exactly the
fix working as designed. The warning correctly classified this as a
"key present, 0 selected — may be a legitimate relevance judgment"
case, not a bug. No "key missing entirely" warning fired in either
round. The one remaining case (a heading present with 0 bullets) is now
fully auditable and distinguishable from a real bug, whereas before
this session it looked identical to one.

Not yet done, low priority: if a future posting reproduces the "key
missing entirely" warning even after this fix, the next step (already
noted in the corrected warning text) is splitting select_bullets() into
one LLM call per heading instead of one call covering all selected
headings — this would rule out output-length/attention degradation on
later headings in a single large completion, which remains a possible
contributing factor this session's evidence couldn't fully separate
from the prompt-ambiguity cause that was fixed.

⸻

FIRST THING TO DO NEXT SESSION

Nothing is blocking. All three items above are built, wired, and
validated against real runs. Suggested priority order for what's next
(from the 2026-08-07 Critic/Revision handoff's original Phase 2 list,
items 1-2 now done):

3. Static HTML Report — resume + cover letter + critique + ATS score +
   revision history + diff report in one generated file (MVP, no
   server — same pattern as the existing `morning` skill). All the
   underlying data (RevisionResult, RoundDiff/SectionDiff, ScoreResult)
   now exists to build this from; it's a rendering task.

4. GUI — project owner's stated eventual goal. critic.py/revision.py/
   diff.py's persistence-agnostic, pure-function design was deliberately
   chosen to make this easy.

5. Resume Scout — resume development of the Scout agent.

6. Scorer — job ranking (scientific fit, location, seniority, visa
   compatibility, salary, user preferences).

7. Local Knowledge Base expansion — publications, patents,
   presentations, research interests, networking contacts, institution
   profiles in Qdrant.

Also worth a look whenever convenient, not blocking:

* A CLI --output-dir flag so verify-writer/verify-revision save actual
  .md files instead of only printing to stdout (raised, not yet built,
  earlier this session).
* Keep an eye on whether critic_review's output quality holds up over
  more postings while still routed to local Ollama instead of Anthropic
  (see the Anthropic-access note at the top of this handoff) — revisit
  roles.yaml once free-tier/API access status changes.

⸻

Recommended Files to Upload (next session)

Core (all touched this session except revision.py/writer.py, still
relevant context)
src/biohunter/selection.py    (bullet-omission fix)
src/biohunter/critic.py       (Score header + parse_score())
src/biohunter/diff.py         (new)
src/biohunter/cli.py          (--show-diff, score display)
src/biohunter/revision.py     (unchanged, but every new piece calls into it)
src/biohunter/writer.py       (unchanged, but WriterDraft is diff.py's input shape)
src/biohunter/llm.py          (unchanged, but json_mode/num_ctx context still relevant)
config/roles.yaml             (unchanged this session, but see Anthropic-access note)

Reference
Resume_Tailoring_3.json
seed_qdrant.js
docs/FILE_TREE.txt            (updated this session — see below)

Latest handoffs
2026-08-07_BioHunter-Critic-Revision-Loop-Handoff.md  (prior session)
this file

⸻

Working Style

Continue the mentoring style used throughout this project:

* Explain rationale before coding.
* Preserve parity/existing guarantees where appropriate — in particular,
  do NOT let a revision, diff, or scoring feature bypass the verbatim-
  catalog-selection guarantee. Every branch in this project is
  deliberately constrained to "choose from the catalog, don't invent."
  Nothing built this session touches that guarantee.
* Avoid unnecessary abstractions. (This session: rejected an early
  two-function draft of diff.py in favor of one function with optional
  labels once the duplication became obvious.)
* Favor incremental, testable milestones over large rewrites.
* If a proposed change would intentionally diverge from prior behavior,
  say so explicitly rather than letting it look like a parity fix. (This
  session: the ATS Score scope discussion explicitly named and rejected
  auto-stop-on-plateau as a real behavior change, not built.)
* No auto-submit / no auto-send — human approval remains the final step
  before application submission. Nothing this session changes this.

New lesson from this session, worth carrying forward: when a warning
message embeds a THEORY about root cause (e.g. last session's "likely a
punctuation mismatch" guess), treat that theory as disprovable, not
fact, until confirmed with --debug evidence — and when it IS disproven,
correct the warning text itself, not just the underlying bug. A stale
theory left in a log message actively misleads the next debugging pass
more than having no theory at all. This is the same "check the shared
cause before patching symptoms" lesson from the prior session, applied
one level up: it applies to your own prior diagnostic guesses too, not
just to the model's bugs.
