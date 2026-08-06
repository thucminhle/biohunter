# Starting the Native Resume/Cover-Letter Pipeline Port — Handoff

Paste this whole document as the first message in a new chat to start this task with full context.

---

## Project summary

BioHunter is a self-hosted, multi-agent job-hunting system (Scout monitors
Bay Area biotech company career pages directly, Scorer ranks postings,
Writer assembles resume + cover letter, Filler auto-fills application
forms for human approval, Networker finds contacts and drafts outreach,
Analyst sends a weekly report — all human-approval-gated for anything
irreversible, no auto-submit/auto-send).

Scorer and Writer were originally designed (ADR-0001) as thin wrappers
around a separate, already-working **n8n + Hermes Agent pipeline**
(Qdrant-backed resume/cover-letter assembly, ATS scoring, LLM critique,
human-approval pause, final Markdown files written to disk). That
pipeline was confirmed production-ready end-to-end as of 2026-08-04
(ADR-0004) — but its one real failure mode (host-level resource
contention between Docker Desktop's VM running n8n and Ollama running
natively on the host) prompted a decision to **retire n8n entirely and
port its logic natively into BioHunter's Writer agent**, rather than keep
n8n as a separate process reached over a webhook (ADR-0005, drafted but
never implemented, is now superseded by this decision).

**This session's task: do that port.** ADR-0006 is the design decision
document for this — read it first, it lays out what's being ported, why,
and a suggested build order.

## Current state

**BioHunter overall:** Phase 1 (Scout + registry) is code-complete,
8/10 target companies live. Phase 2 (Scorer/Writer) has not started any
implementation yet — only design/decision work (ADR-0001 through
ADR-0006).

**This specific task:** Not started. This is the first session working
on it. ADR-0006 was just accepted; nothing has been built yet.

**n8n pipeline being ported (the thing this session ports):** Fully
working, end-to-end, as of 2026-08-04 — see the detailed handoff below
for its exact architecture, gotchas, and root-caused failure mode. That
pipeline is the reference implementation to port faithfully first, then
diff against if anything looks off, per ADR-0006's explicit instruction
not to improve prompts/selection quality in the same pass as the
migration.

## What this session should do

**Important gap found before this session starts: `LLMClient` does not
exist yet.** The design doc (§3) sketches the interface and a
provider-per-role `config/roles.yaml`, but it was never built. Every step
below depends on it, so it's Step 0, done first, not discovered mid-port.

**Step 0 — Build `LLMClient` before anything else.**

- One interface: `chat(messages, tools?) -> response`.
- Two backend classes are enough, not three:
  - `AnthropicClient` — Anthropic's own SDK/schema, for cloud calls
    (`writer_coverletter`, `networker_email` per the existing
    `roles.yaml` sketch).
  - `OpenAICompatibleClient` — one class for **both** Ollama and MLX,
    since both expose the same `/v1/chat/completions` schema. Ollama
    serves this at `localhost:11434`; MLX serves the same shape via
    `mlx_lm.server` (e.g. `uvx --from mlx-lm mlx_lm.server`, default
    `localhost:8080`). Only `base_url` and `model` differ between the two
    — don't write separate `OllamaClient`/`MLXClient` classes, it's
    unnecessary duplication.
- Model selection is config-driven, not hardcoded: `config/roles.yaml`
  maps each role to a `provider` + `model` (+ `base_url` for the
  OpenAI-compatible backend, since Ollama and MLX run on different
  ports). Adding a new local model or switching a role from Ollama to MLX
  should be a one-line config change, never a code change.
- **Decision made: also support a per-run CLI override**, e.g.
  `biohunter run --model writer_selection=llama3.1:8b`, so a single model
  can be swapped for one invocation without editing `roles.yaml` and
  reverting it afterward. Build this into `LLMClient`'s config-loading
  from the start (accept an optional override dict, merge over whatever
  YAML loaded) rather than retrofitting it later — this was decided
  specifically because comparing local-model quality against the n8n
  reference implementation (see step 1 below) will mean poking at
  different models repeatedly, and a YAML-edit-per-try would get old
  fast. Needs a small amount of CLI arg parsing in `cli.py` too, not just
  `LLMClient` itself.
- Verify with a trivial round-trip call to each of the three providers
  (Anthropic, Ollama, MLX) before building anything that depends on it —
  including at least one call using the `--model` override, to confirm
  the override path works before it's relied on for parity-checking.

Per ADR-0006's suggested build order, once Step 0 is working:

1. Port Qdrant retrieval + the 8 selection branches (resume:
   summary/headings/bullets/skills; cover letter:
   intro/story/impact/gratitude) into Writer, using BioHunter's
   `LLMClient` abstraction and a Qdrant Python client against the
   existing `resume_content` collection. Check output parity against the
   n8n workflow's existing behavior for a few known postings before
   moving on.
2. Port the ATS-scoring + critique step natively — this doubles as
   ADR-0002's planned Critic step (blind-review pass, no shared context
   with Writer's own prompt), so it should be built once, not twice.
3. Add an `awaiting_review` posting status + a human-approval gate
   (replaces `Wait (Form)` — just a status check before finalizing files,
   no per-execution pause semantics needed).
4. Stop there for this session unless there's clear runway — score-
   threshold auto-triggering and the static HTML report (also in
   ADR-0006) are separate, later steps; don't start them until 1–3 are
   confirmed working end-to-end.

Do **not** start on: score-threshold auto-trigger logic, the `biohunter
report` command, or any dashboard work — all explicitly out of scope for
this session per ADR-0006's build order and the "MVP first, refine after"
direction this task was scoped under.

## Known gotchas to carry over from the n8n implementation (don't re-litigate)

These are documented in the 2026-08-04 handoff (attach it — full detail
below) and apply just as much to a native Python port:

- Qdrant collection is `resume_content` (768-dim, Cosine) — not
  `resume_components`. Confirm via `curl http://localhost:6333/collections`
  if in doubt.
- Exact-string matching between LLM selection output and catalog labels
  needs a logged warning + fallback-to-first-entry, never a silent drop —
  this was implemented per-branch in n8n (8 times); the ported version
  needs the same defensive handling, ideally as one shared helper instead
  of copy-pasted 8 times.
- Any regex/JSON parsing of LLM output must match the model's actual
  output format exactly — this bit the n8n version repeatedly; worth
  testing against real model output early, not assuming a format.
- The cover-letter "stitch" pass (`edit cover letter` node) does a light
  edit across the merged intro/story/impact/gratitude selections — this
  logic needs to be ported too, not just the four selection branches
  feeding it.

## Working style

- Mentoring mode, not autopilot — walk through the port step-by-step,
  explain what's being built and why. Low-level/teachable code should be
  written out for me to type/apply myself with guidance; heavier
  implementation (e.g. the full selection-branch logic) is fine to write
  directly, but explain what it does rather than handing it over silently.
- Comfortable with architecture/design decisions already made (ADR-0006)
  — no need to re-litigate those; focus on implementation.
- Still building git/terminal fluency — explicit step-by-step commands
  with expected output, one command at a time when troubleshooting.
- I paste back exact terminal output — use it to diagnose precisely.
- Prefer file-based deliverables (single named file, not zipped folders)
  for small changes; for anything nontrivial, prefer a full-file sync
  over incremental patches (a partial-apply once caused a command to
  silently go missing — see `docs/handoffs/2026-07-29-*.md`). If sending
  an incremental patch anyway, say so explicitly and tell me to run
  `git status`/diff right after applying it.

## Files to attach to your first message in the new session

1. **This document** — the task, current state, build order, gotchas.
2. **`docs/adr/0006-native-pipeline-auto-writer-static-report.md`** — the
   design decision driving this session; defines scope and build order.
3. **`docs/adr/0004-n8n-pipeline-production-ready.md`** — describes the
   n8n pipeline's architecture (8 parallel branches) being ported.
4. **`docs/adr/0002-adopt-patterns-from-jht.md`** — defines the Critic
   step (blind-review) this session also builds, per ADR-0006 step 2.
5. **`docs/handoffs/2026-08-04-resume-pipeline-e2e-complete.md`** — full
   architecture diagram, root-caused failure mode, and all "known
   gotchas" for the pipeline being ported. This is the most detailed
   reference for exactly what needs to be reproduced.
6. **The n8n workflow export** (n8n UI → Workflow menu → Download) —
   **important, not previously attached anywhere:** this JSON has the
   actual node configs and exact selection/critique prompts the port
   needs to reproduce faithfully. The handoff docs describe the
   architecture; the export has the literal prompt text.
7. **`seed_qdrant.js`** — confirms the `resume_content` collection's
   schema and payload field names, needed to write correct Qdrant queries
   in Python.
8. **`config/roles.yaml`** — current provider/model config, needed to
   confirm what Step 0's `LLMClient` needs to read and whether the
   provider names in it (`ollama`, `anthropic`) need an `mlx` option
   added alongside.
9. **`docs/FILE_TREE.txt`** — so the new session sees what already exists
   (`src/biohunter/db.py`, `src/biohunter/config.py`, etc.) before writing
   anything new. Note: per the gap found this session, `LLMClient` does
   **not** exist yet despite being in the design doc — don't expect to
   find it in the tree.

`docs/ROADMAP.md` and ADR-0001/0005 are optional — useful for background
on why the earlier webhook approach was superseded, but not required to
do the port itself.
