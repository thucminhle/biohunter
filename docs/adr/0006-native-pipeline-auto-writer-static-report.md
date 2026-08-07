# ADR-0006: Port the resume/cover-letter pipeline natively into BioHunter; auto-trigger Writer above a score threshold; static HTML activity report (MVP scope)

**Status:** Proposed
**Date:** 2026-08-05
**Supersedes:** ADR-0001 (thin-wrapper-around-n8n-hermes) — see Context
**Supersedes/narrows:** ADR-0005 (async webhook contract) — moot once there's
no second process to call; see Consequences

## Context

ADR-0001 chose to keep Scorer/Writer as thin wrappers around an external
n8n + Hermes pipeline rather than reimplementing scoring/resume-assembly
logic, explicitly leaving the door open to revisit "if n8n becomes a
bottleneck (e.g. webhook latency, single point of failure)." ADR-0004
confirmed that pipeline as production-ready, and the 2026-08-04 handoff
root-caused its one real failure mode: **host-level resource contention
between Docker Desktop's VM (running n8n) and Ollama running natively on
the host**, surfaced as n8n task-runner heartbeat/timeout errors under
concurrent LLM load, fixed by a full Docker Desktop restart.

That fix works, but the underlying failure domain — a VM boundary between
the orchestrator and the local model — still exists and can recur under
load. ADR-0005 designed around keeping that boundary (async webhook,
polling, Captain serialization). This ADR instead asks whether to remove
the boundary entirely, since everything the n8n workflow does (Qdrant
retrieval, LLM selection calls, an approval pause, a file write) is
already inside BioHunter's own planned architecture:

- Qdrant selection branches → BioHunter's `LLMClient` + Qdrant Python
  client, same collection (`resume_content`)
- Cover-letter stitch pass → another `LLMClient` call, routed per
  `config/roles.yaml` like any other role
- ATS scoring + critique → same, and doubles as ADR-0002's planned Critic
  step (blind-review pass) rather than a separate thing to build later
- `Wait (Form)` human approval → the same human-approval-gate pattern
  Filler/Networker already require by design (§12 of the design doc) —
  one approval mechanism instead of two
- Final file write → plain `fs`, no Docker bind-mount workarounds needed

The user also asked two follow-on questions this ADR folds in: whether
Writer can auto-trigger on well-matched postings without a human asking
per-posting, and whether BioHunter's activity can be visualized. Per
explicit direction: **this ADR scopes an MVP.** The dynamic/interactive
dashboard question raised in conversation is deliberately deferred, not
answered here — see ADR-0002's prior rejection of a web dashboard for the
reasoning that still applies, and revisit only once there's a concrete
need, per the project's stated working style.

## Decision

### 1. Port the pipeline natively; retire the n8n dependency

Rebuild the pipeline's logic as part of BioHunter's Writer agent, in
Python, using pieces already planned in the design doc rather than new
infrastructure:

- Qdrant queries against the existing `resume_content` collection —
  same shape as the 8 n8n branches (summary/headings/bullets/skills;
  intro/story/impact/gratitude), just called directly instead of via
  n8n's fetch→format→select→parse node chain.
- One `LLMClient` call per selection branch, using whatever model
  `config/roles.yaml` assigns to that role — mirrors the n8n workflow's
  branch structure closely enough that the port is mostly "move this
  logic from n8n nodes into Python functions," not a redesign.
- ATS scoring + critique becomes ADR-0002's Critic step, done natively —
  one blind-review LLM call, no shared context with Writer's own prompt.
- Human-approval pause becomes BioHunter's own gate: Writer produces a
  draft, posting status flips to `awaiting_review`, and nothing further
  happens until the human approves — no `Wait (Form)`, no per-execution
  pause semantics to design around.
- Final resume + cover letter written to disk as before (same Markdown
  file output), just via a normal `fs` write in the same process.

**MVP scope note:** for the first cut, port the branch logic as directly
as possible — same catalogs, same selection prompts, same critique step —
rather than improving prompts/selection quality at the same time as the
migration. Prompt/quality refinement is a separate, later pass once the
port is confirmed working end-to-end, consistent with "build MVP first,
refine after."

### 2. Auto-trigger Writer above a score threshold

Add a configurable score threshold (e.g. `config/search_criteria.yaml` or
`roles.yaml`). Captain's run loop becomes:

```
Scout  → new postings → status: new
Scorer → scores each  → status: scored
  if score >= threshold: auto-invoke Writer → status: awaiting_review
  else:                                        stays at status: scored
```

This does not cross the project's existing guardrail. The hard rule from
§12 of the design doc is *no auto-submit, no auto-send* — actions with an
external, hard-to-undo consequence. Generating a draft resume/cover letter
is the same category of thing Writer already does on request; only the
trigger (score threshold instead of a manual ask) changes. Filler and
Networker remain exactly as human-gated as designed; nothing about this
decision touches them.

**Explicitly deferred, not decided here:** what happens at a borderline
score — auto-generate anyway (bounded by ADR-0002's weekly budget log) vs.
queue for a manual "generate this one" nod first. Per the MVP-first
direction, ship with a single hard threshold now; revisit borderline
handling once real score distributions are visible.

### 3. Static HTML activity report (MVP), dynamic dashboard deferred

Add a `biohunter report` command that queries SQLite and renders a single
static HTML file — no server, no framework, same pattern as the existing
`morning` skill's generated brief. Contents, mirroring Analyst's planned
weekly-digest shape (§8 of the design doc) but generated on demand rather
than only on a Sunday cron:

- New postings this run, grouped by company, with scores
- Postings auto-sent to Writer (above threshold) vs. sitting at `scored`
- Drafts awaiting your review vs. already reviewed
- Any pipeline errors (failed LLM calls, Qdrant misses) from this run

This directly answers "visualize BioHunter's activity" without reopening
ADR-0002's dashboard rejection — it's a generated file you open, not a
running service. **The dynamic/interactive dashboard question (live
updates, click-through, etc.) is deliberately left open per explicit
direction to revisit after the MVP is built**, not decided in this ADR
either way.

## Alternatives considered

- **Keep n8n, proceed with ADR-0005's async webhook design** — rejected
  for now: removes an entire failure domain (Docker VM / native-Ollama
  contention) rather than designing carefully around it, and the port
  reuses architecture BioHunter already planned to build anyway (Qdrant
  client, `LLMClient`, Critic step), so it isn't net-new scope, it's
  scope that was coming either way, just pulled into one place.
- **Port the pipeline but keep prompt/selection-quality improvements in
  the same pass** — rejected: conflates a migration with a refinement,
  making it harder to tell whether a bug is "the port is wrong" or "the
  new prompt is worse." Port first, verify parity, refine after.
- **Auto-trigger Writer with no threshold (always generate)** —
  rejected: defeats the purpose of scoring at all, and burns cloud budget
  (ADR-0002's cost-log concern) on clearly-bad matches.
- **Build the dynamic dashboard now, since the question was asked** —
  rejected per explicit direction: MVP first. Also consistent with
  ADR-0002's original reasoning for rejecting a dashboard (solves a scale
  problem this single-user tool doesn't have) — worth deciding on purpose
  later, not by momentum now.

## Consequences

- **ADR-0001 is superseded.** Its "thin wrapper" decision no longer
  applies once the logic is ported; ADR-0001's Status should be updated
  to `Superseded by ADR-0006` rather than deleted, so the history of why
  the original call was made stays intact.
- **ADR-0005 becomes moot.** There's no second process to call, so the
  webhook trigger/contract/polling design it specifies has nothing to
  connect to. Mark it `Superseded by ADR-0006` rather than implementing
  it. (No wasted work — ADR-0005 was never built, only drafted.)
- **n8n workflow itself is not deleted**, just no longer in BioHunter's
  critical path — keeping it around costs nothing and gives a reference
  implementation to diff the ported logic against if selection quality
  regresses during the port.
- Removes the Docker Desktop dependency from BioHunter's runtime path
  entirely — one fewer process, one fewer failure domain, no more
  `host.docker.internal`/vpnkit boundary between the orchestrator and
  Ollama.
- ADR-0002's planned Critic step is no longer a separate future addition
  — it's built as part of this port, pulled forward from "Phase 2, target"
  to "now."
- Loses n8n's visual per-branch debugging (seeing each selection branch's
  output in the UI). MVP scope accepts this; if it's missed in practice,
  add lightweight per-branch logging to the ported Python code rather
  than reintroducing n8n.
- Seed data (`resume_content` Qdrant collection, `seed_qdrant.js`) is
  reused as-is — no reseeding needed, only the client calling it changes
  language/location.
- Borderline-score handling and the dynamic dashboard are both explicitly
  open questions for a future ADR, not silently decided by omission here.

## MVP build order (suggested, not binding)

1. Port Qdrant retrieval + selection-branch logic into Writer (parity
   check against n8n's existing output for a few known postings).
2. Port critique step as the Critic (ADR-0002), wire into Writer's flow.
3. Add `awaiting_review` status + human-approval gate (no `Wait (Form)`
   equivalent needed — just a status check before file finalization).
4. Add score-threshold config + Captain auto-trigger logic.
5. Add `biohunter report` static HTML command.
6. Only after 1–5 are working end-to-end: revisit borderline-score
   handling and whether a dynamic dashboard is actually wanted.

Addendum (2026-08-07): the n8n export was deleted rather than retained. The original rationale (diffing against it if selection quality regressed) was superseded once the native pipeline was validated directly against real postings via Critic + the Revision Loop, making a diff-against-n8n fallback unnecessary in practice.
