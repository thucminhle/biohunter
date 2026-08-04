# ADR-0004: n8n + Hermes resume/cover-letter pipeline is production-ready; Phase 2 webhook integration is unblocked

**Status:** Accepted
**Date:** 2026-08-04

## Context

ADR-0001 committed BioHunter's Scorer and Writer agents to delegating to
an existing external n8n + Hermes Agent pipeline via webhook, rather than
reimplementing scoring/resume-assembly logic. At the time, that pipeline
was still under active development in a separate debugging track (see
`docs/handoffs/2026-08-04-resume-pipeline-e2e-complete.md` for the full
history), most recently stuck on an intermittent n8n task-runner error
during the cover-letter branch expansion (4 → 8 parallel selection
branches).

That error is now resolved and root-caused: it was host-level resource
contention between Docker Desktop's VM (running n8n) and Ollama (running
natively on the host) under concurrent LLM call load — not a defect in
the workflow's design, node count, or code. Fix was a full Docker Desktop
restart to clear degraded VM state; mitigations if it recurs are
documented in the pipeline handoff.

The pipeline now runs cleanly end-to-end: form submission → 8 parallel
Qdrant/LLM selection branches (resume: summary/headings/bullets/skills;
cover letter: intro/story/impact/gratitude) → draft assembly → ATS
scoring → LLM critique → human-approval form pause → revised final resume
+ cover letter written to disk as separate Markdown files.

This is the first point since ADR-0001 was written where the external
dependency it names is actually confirmed stable, so it's worth recording
as its own decision point rather than silently assuming Phase 2 can start.

## Decision

Mark the n8n/Hermes pipeline as **ready to integrate** and unblock Phase 2
(Scorer/Writer hooks) on that basis, with three integration questions
called out as needing explicit decisions before webhook code is written
— not discovered mid-integration:

1. **Trigger shape.** The pipeline is currently triggered via `On form
   submission`. Phase 2 needs either a proper n8n **Webhook** trigger node
   added alongside/instead of the form trigger, or a way for BioHunter's
   Writer agent to submit to the existing form trigger programmatically.
   This is n8n configuration work, not a pipeline redesign.
2. **Webhook contract.** What BioHunter posts in (posting title,
   description, company — matches what `split jobs` already parses from
   its block-text input, so the contract is likely a structured-JSON
   version of that same shape) and what it returns (resume section text?
   file paths on disk? the assembled cover letter before or after the
   `edit cover letter` stitch pass?) needs to be decided explicitly, since
   the pipeline currently writes final output to disk rather than
   returning it in an HTTP response.
3. **Per-item Wait(Form) limitation.** The pipeline's human-approval step
   pauses the *entire* n8n execution, not per-item (known limitation,
   documented, intentionally out of scope to fix). If BioHunter ever POSTs
   more than one posting concurrently, this needs to be accounted for in
   Captain's orchestration (e.g. serialize Writer calls, or accept that a
   second POST during an open approval-wait will queue/block) — this
   should be designed for up front rather than discovered as a bug later.

## Alternatives considered

- **Start Phase 2 webhook work immediately without resolving the three
  questions above** — rejected: the same project pattern that led to
  ADR-0001 (avoid two sources of truth, avoid rework) argues for deciding
  the contract once rather than wiring a webhook against a form-submission
  trigger and reworking it once the real contract is clear.
- **Wait for BioHunter's own registry (7/10 → 10/10 companies) to fully
  complete before touching Phase 2 at all** — rejected: registry
  completion (Exelixis, Scribe Therapeutics per ADR-0003) and Phase 2
  webhook design are independent workstreams; there's no dependency
  forcing serialization, and the pipeline being newly stable is a natural
  moment to at least design the contract even if implementation waits.

## Consequences

- `ROADMAP.md` Phase 2 gets its first checklist items broken out with the
  three specific integration decisions above, instead of a single opaque
  "n8n webhook client for scoring" line.
- ADR-0001's stated retry/backoff mitigation ("Captain should retry with
  backoff and flag stalled postings rather than fail silently") should be
  read alongside this ADR's root-cause note — the specific failure mode to
  design retry logic around is host-resource-contention-driven n8n
  unresponsiveness, not just generic downtime.
- No code changes yet — this ADR unblocks Phase 2 planning/design, not
  Phase 2 implementation. Implementation still starts fresh in a future
  session per `HANDOFF.md`'s working style.
