BioHunter — Critic + Revision Loop Handoff (2026-08-07)

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

Phase 1 (native Writer port) is complete and was handed off in
2026-08-06_BioHunter-Phase-2-Development.md. This handoff covers the two
Phase 2 items built since then — Critic and the Revision Loop — plus an
unresolved data-quality issue found while testing them against a real
posting that should be the FIRST thing the next session verifies before
building anything further on top of Writer.

⸻

Current Status

Phase 2, items #1–#2 — Critic + Revision Loop

Status: Built and wired end-to-end. NOT yet validated as producing
reliable output — see "Open Issue" below before trusting it or building
on it.

Implemented:

* src/biohunter/critic.py — critique_draft(): one blind-review LLM call
  over an assembled WriterDraft. Freeform text output organized under six
  fixed markdown headers (ATS & Keyword Coverage / Unsupported Claims /
  Weak Bullets / Weak Summary / Cover Letter Critique / Overall
  Recommendation). Deliberately NOT built on selection.py's
  catalog-matching machinery — there's no catalog to select from here.
  DB/persistence-agnostic by design.

* src/biohunter/revision.py — run_revision_loop(): draft → critique →
  (revise → critique) × revision_rounds, returning a RevisionResult with
  the final draft/critique plus a full round-by-round history
  (RevisionRound list). revision_rounds=2 means 3 drafts/3 critiques
  total, matching the original handoff's "revision_rounds: 2" example.
  Also DB/persistence-agnostic — no awaiting_review status writes, no
  storage. That's an intentional seam: a future Captain auto-trigger
  path or a GUI backend decides what to persist, this module just
  produces the data.

* config/roles.yaml — new critic_review role, routed to Anthropic
  (same reasoning as writer_coverletter/networker_email_draft: a blind
  quality review is exactly the low-volume, quality-sensitive call this
  project already reserves for cloud).

* Revision mechanism: every selection function in selection.py
  (select_variant, select_headings, select_bullets, select_skills,
  stitch_cover_letter) and writer.generate_draft() gained an optional
  critique_feedback: str | None = None param. When set, it's appended
  as extra context to that branch's existing prompt so the model can
  pick DIFFERENTLY this round — critically, revision still goes through
  the same verbatim-catalog-selection functions as a first draft, never
  a free-rewrite path. This was a deliberate design choice: a revision
  pass that just says "rewrite this given feedback" would break the
  no-invented-facts guarantee every branch in this project enforces.
  None (the default) reproduces the exact original prompt — zero
  behavior change for any pre-existing caller.

* CLI: verify-critic (Writer once + Critic once) and verify-revision
  (full loop, --revision-rounds N, prints every round's draft sections +
  critique) — both mirror verify-writer's existing shape.

⸻

Bug found + partially fixed during testing: silent-empty selections

While testing verify-revision against a real posting (Guardant Health,
Senior Scientist Mass Spec), the resume came back with Professional
Experience and Key Skills sections COMPLETELY EMPTY, and
summary/intro/story selections were stuck on selected_label: None every
round (meaning critique feedback was having zero visible effect on those
branches — they were falling back to catalog[0] regardless, both before
and after "revision"). Cover letter output also had the model's own
meta-commentary ("Okay, here's the final letter text...") leaking into
the actual letter body.

Root cause identified: none of the LLMClient backends were forcing
JSON-mode output. select_variant/select_headings/select_bullets/
select_skills all ask the model to "Respond with ONLY valid JSON" in the
prompt text, but nothing constrained generation to actually produce it —
Ollama was left to comply from instructions alone.

Fixed (already in the codebase you're reading):

* llm.py — both OllamaNativeClient and OpenAICompatibleClient now accept
  a backend-agnostic json_mode kwarg. Ollama: sets native format:"json".
  OpenAI-compatible: sets response_format:{"type":"json_object"} (NOT
  YET VERIFIED against a real MLX/oMLX server — no role currently routes
  there for real work, so this is untested in practice).
* selection.py — the 4 schema-dependent branches now pass json_mode=True.
  stitch_cover_letter deliberately does NOT (it's meant to return free
  text, not JSON).
* selection.py — added warnings for the specific silent-empty case that
  caused the bug: select_bullets now warns when a heading had catalog
  bullets available but 0 were selected; select_skills warns the same
  way. Previously these were silent because the existing warning only
  fired on INVALID picks, not on zero picks.
* selection.py — stitch_cover_letter now defensively trims a leaked
  meta-commentary preamble, by cutting back to the first line matching
  ^\s*Dear\b if the response doesn't already open on one.
* cli.py — new global --debug flag (before the subcommand:
  python -m biohunter.cli --debug verify-revision ...) that enables
  logger.debug output, which now includes every branch's raw LLM
  response text before parsing — added specifically so a future failure
  like this shows what the model actually said, not just that parsing
  failed.
* llm.py + roles.yaml — added num_ctx as role-level config (same pattern
  as base_url/api_key), auto-applied to every call for that role.
  Rationale: Ollama's own default context window per REQUEST can be far
  smaller than a model's advertised max (historically 2048-4096 tokens)
  unless explicitly set — meaning a role could be pointed at a
  256K-context model and still silently truncate a long catalog+critique
  prompt if nothing sets num_ctx. This is a genuinely separate axis from
  "which model is loaded" — a too-small effective context window would
  produce the exact same symptoms as a too-weak model (instructions at
  the front of the prompt pushed out, longer prompts degrading worse
  than shorter ones), which is exactly the pattern seen in this session's
  bullets branch (round 2, with critique feedback appended, regressed
  vs. round 1). Set to 8192 for writer_selection — deliberately generous
  for what's actually being sent (skills catalog: 27 items; bullets: up
  to 300 fetched candidates), not a guess at either candidate model's
  true max. Only wired for the ollama provider (OllamaNativeClient nests
  it under the native "options" field); OpenAICompatibleClient pops and
  drops it, since MLX/oMLX-style servers have no per-request equivalent.

⸻

RESOLVED (2026-08-07, same session) — model choice was the dominant
factor, not num_ctx

Re-tested with `ollama ps` confirming gemma4:12b-mlx actually loaded
(262144 context, 7.5-17GB resident, matching roles.yaml's documented
model) rather than whatever was resolving before. Result: skills
selection now returns correctly-shaped separate array elements (Key
Skills section populated for the first time this session), cover-letter
intro/story labels are exact full-string matches (no more truncated
"Template A" / "Agilent"), the cover-letter stitch opens cleanly on
"Dear Hiring Manager" both rounds with no leaked preamble, and — for the
first time — round 2 visibly incorporated round 1's critique (added
"PRM," "lipidomics," "CLIA/FDA," "LLOQ/ULOQ" in direct response to what
Critic flagged as missing). Critique quality itself was sharp and
specific both rounds (unsurprising — critic_review was always Anthropic,
unaffected by any of this session's Ollama-side changes; it simply had a
populated resume to critique against for the first time).

Correction on num_ctx: `ollama ps` during this run showed gemma4:12b-mlx
loaded at 262144 context, NOT the 8192 set in roles.yaml this session.
That means the num_ctx fix was not the binding constraint in this test —
Ollama loaded the model at its full native/Modelfile-declared context
regardless of the smaller value requested. Since an explicit num_ctx
could plausibly override a model's own default DOWNWARD rather than
only protect against a too-small one, and the project owner's real run
never actually applied this session's roles.yaml, num_ctx: 8192 was
REMOVED from writer_selection after the fact (2026-08-07, same session)
rather than kept as a now-unproven guess that could regress a
configuration already shown to work. The num_ctx plumbing itself (role-
level config, threaded through LLMClient -> OllamaNativeClient's
"options" field) is still in llm.py and still worth keeping as
available infrastructure — add a value back only for a specific role/
model combination whose own default proves too small, sized to what
THAT model actually needs, not a blanket guess.

Residual, minor, non-blocking issue: a heading still occasionally gets 0
bullets despite catalog bullets being available — Biomarker Strategy &
Translation (round 1) and Selected Research & Translational Impact
(round 2, a heading added on top of round 1's set, presumably from
critique feedback broadening the selection). This is now an occasional
edge case affecting the 3rd/4th selected heading, not the systemic
failure seen earlier this session. Worth a follow-up look (possibly the
same "collapse everything into fewer items" tendency seen in skills,
just less severe now with a capable model + json_mode) but does not
block moving on to Phase 2 items #1-4 below.

FIRST THING TO DO NEXT SESSION

The root cause is resolved (see above) — Phase 2 items #1-4 below are
UNBLOCKED. Two small follow-ups, neither blocking:

1. Investigate the residual occasional zero-bullet heading (see above) —
   low priority, low frequency, doesn't warrant holding up other work.
2. num_ctx: 8192 was removed from writer_selection after the fact (see
   correction above) — no action needed unless a future model swap for
   this role shows truncation symptoms, at which point size num_ctx to
   that specific model's actual needs rather than reusing this session's
   guess.

⸻

Phase 2 Objectives (unchanged from prior handoff, reordered)

1. Resume Diff — show what changed between rounds. run_revision_loop()
   already returns RevisionResult.rounds, a full list of
   (draft, critique) per round, so the raw material for a diff already
   exists; this is now a rendering task, not a data-plumbing one.

2. ATS Score — Critic's output is intentionally freeform prose right now
   (project owner's explicit choice — see prior handoff), so there is no
   numeric score to show yet. Two paths discussed, not yet decided:
   extend critique_draft()'s prompt to also emit a small structured
   ## Score block the caller parses out (cheapest, one prompt change,
   keeps everything in one LLM call), vs. a separate purpose-built
   scoring function (cleaner separation, costs another LLM call + role).
   Also worth noting from this session's critique output: Critic's own
   header usage already drifts slightly round to round ("## Weak
   Summary" vs "## Summary", ad hoc "Rating: X/10" bullets appearing
   unprompted in round 1 but not round 2) — if a future score-parsing
   step needs to rely on exact header text, the critique prompt likely
   needs tighter format constraints (or its own json_mode-style
   enforcement) first.

3. Static HTML Report — resume + cover letter + critique + ATS score +
   revision history + diff report in one generated file (MVP, no
   server — same pattern as the existing `morning` skill).

4. GUI — project owner's stated eventual goal: display tailored resume,
   cover letter, critique, and ATS score together. critic.py and
   revision.py's persistence-agnostic design (pure functions returning
   data, no DB writes) was deliberately chosen to make this easy — a GUI
   backend can call run_revision_loop(), get a RevisionResult, and
   decide what to store/show without either module knowing about a
   database or a UI. Worth returning to once item 0 is resolved and the
   diff/score pieces exist to show.

5. Resume Scout — resume development of the Scout agent.

6. Scorer — job ranking (scientific fit, location, seniority, visa
   compatibility, salary, user preferences).

7. Local Knowledge Base expansion — publications, patents,
   presentations, research interests, networking contacts, institution
   profiles in Qdrant.

⸻

Recommended Files to Upload (next session)

Core (all touched this session)
src/biohunter/llm.py
src/biohunter/selection.py
src/biohunter/writer.py
src/biohunter/critic.py       (new)
src/biohunter/revision.py     (new)
src/biohunter/cli.py
config/roles.yaml
src/biohunter/qdrant.py       (unchanged, but relevant context)

Reference
Resume_Tailoring_3.json
seed_qdrant.js
docs/FILE_TREE.txt

Latest handoffs
2026-08-06_BioHunter-Phase-2-Development.md  (Phase 1 completion)
this file

⸻

Working Style

Continue the mentoring style used throughout this project:

* Explain rationale before coding.
* Preserve parity/existing guarantees where appropriate — in particular,
  do NOT let a revision or scoring feature bypass the verbatim-catalog-
  selection guarantee by introducing a free-rewrite path. Every branch
  in this project is deliberately constrained to "choose from the
  catalog, don't invent."
* Avoid unnecessary abstractions.
* Favor incremental, testable milestones over large rewrites.
* If a proposed change would intentionally diverge from prior behavior,
  say so explicitly rather than letting it look like a parity fix.
* No auto-submit / no auto-send — human approval remains the final step
  before application submission. Nothing in Critic/Revision changes
  this; both still stop at producing a draft + critique for review.

One thing to add to that working style based on this session: when a
selection branch's output looks suspicious (empty section, repeated
identical fallback, garbled JSON), don't assume it's a small code bug in
isolation — check whether it's actually one symptom of a single
underlying cause (in this case, likely model capability) before
patching each symptom separately. The --debug flag added this session
exists specifically to make that check fast next time.
