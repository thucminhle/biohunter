# ADR-0001: Scorer and Writer are thin wrappers around existing n8n + Hermes Agent, not reimplemented

**Status:** Accepted
**Date:** 2026-07-26

## Context

I already have a working n8n workflow with Hermes Agent that scores job postings and assembles tailored resumes from preformed bullet sections. BioHunter needs scoring and resume-writing capability as part of its pipeline.

## Decision

BioHunter's Scorer and Writer agents do **not** reimplement scoring/resume-assembly logic. Instead:
- Scorer POSTs posting data to the existing n8n webhook and stores the returned score + rationale.
- Writer calls the n8n resume-assembly webhook for resume sections, and only adds its own LLM call for the cover letter + tailoring rationale (which n8n doesn't currently produce).

## Alternatives considered

- **Reimplement scoring natively in BioHunter** — rejected: duplicates working logic, creates two sources of truth that can drift, more code to maintain.
- **Migrate the n8n workflow into BioHunter entirely** — rejected for now: n8n workflow is actively being iterated on separately; forcing a migration now would slow both projects down. Revisit if n8n becomes a bottleneck (e.g. webhook latency, single point of failure).

## Consequences

- BioHunter stays decoupled and simpler; changes to scoring logic happen in one place (n8n).
- Adds a runtime dependency: BioHunter can't score/assemble resumes if n8n is down. Mitigation: Captain should retry with backoff and flag stalled postings rather than fail silently.
- If n8n/Hermes is ever replaced, only the webhook call sites in Scorer/Writer need to change — not the rest of the pipeline.
