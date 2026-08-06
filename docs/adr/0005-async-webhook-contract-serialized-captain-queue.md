# ADR-0005: Webhook trigger runs alongside the form trigger; contract is async/poll-based; Captain serializes Writer calls

**Status:** Proposed
**Date:** 2026-08-05

## Context

ADR-0004 confirmed the n8n/Hermes pipeline is production-ready and unblocked
Phase 2, but explicitly called out three integration decisions that needed
to be made *before* webhook code is written, not discovered mid-integration:

1. Trigger shape (form trigger vs. webhook trigger)
2. Webhook request/response contract
3. How Captain handles the pipeline's per-execution (not per-item)
   human-approval `Wait (Form)` step if more than one posting is in flight

This ADR resolves all three together, since the answer to #2 depends
directly on a property of the pipeline that also drives #3: the
`Wait (Form)` step means a single pipeline run can be paused for an
indeterminate amount of time (minutes to days) waiting on a human. Any
contract or concurrency design has to be built around that, not around
the assumption that a "webhook call" completes quickly.

## Decision

### 1. Trigger shape: add a Webhook node, keep the form trigger

Add an n8n **Webhook** trigger node to the existing workflow, wired into
the same downstream path as `On form submission` (both feed `split jobs`).
Do not remove the form trigger.

- The form trigger stays for manual runs/dev-testing of the pipeline
  independent of BioHunter — useful, and free to keep.
- BioHunter's Writer gets a stable JSON-in HTTP endpoint instead of having
  to script against a form-submission URL, which is designed for browser
  multipart submissions and would tie BioHunter's request shape to the
  form's HTML fields rather than a clean contract.

### 2. Contract: async, poll-based — not request/response

A synchronous webhook (hold the HTTP connection open until the whole
pipeline finishes) doesn't work here, because the pipeline includes a
human-approval pause of unknown duration. Instead:

**Request** — `POST` to the new Webhook node, JSON body matching what
`split jobs` already parses (no new parsing logic needed in n8n):

```json
{
  "posting_id": "<BioHunter posting_id — new field, see Consequences>",
  "company_name": "...",
  "job_title": "...",
  "job_description": "...",
  "think": "<optional, matches split jobs' existing 4th field>"
}
```

**Response** — the Webhook node responds immediately (does not wait for
the run to finish):

```json
{ "execution_id": "<n8n execution id>", "status": "queued" }
```

**Completion** — Captain polls n8n's own REST API
(`GET /api/v1/executions/{execution_id}`) on a backoff schedule (e.g. every
2 minutes) rather than the workflow exposing a second custom "status"
endpoint. Once the execution status is `success`, Captain reads the final
resume/cover-letter file paths directly off the shared filesystem — the
pipeline already writes these to disk today (per the 2026-08-04 handoff),
so nothing about the pipeline's last two Code nodes needs to change to
return content inline over HTTP.

This relies on BioHunter and n8n running on the same machine (true today —
both on your Mac per `HANDOFF.md`). Flagged explicitly in Consequences
since it's a new implicit constraint this ADR introduces.

### 3. Concurrency: Captain serializes Writer calls, one in flight at a time

Because `Wait (Form)` pauses the *entire* execution, not per-item, Captain
must not let a second posting reach the webhook while one is already
in flight.

- Add a `pipeline_status` field (postings table or a small side table):
  `not_started` → `queued` → `awaiting_approval` → `complete` / `error`.
- Before Writer POSTs a new posting, Captain checks whether any posting is
  currently `queued` or `awaiting_approval`. If so, the new posting is left
  at `pending_writer` and Captain retries it on a later pass — it does not
  POST yet.
- When the in-flight posting's execution reaches `success` via polling,
  Captain is clear to pop the next `pending_writer` posting and POST it.

This turns the documented "known limitation" into an explicit,
deterministic single-in-flight queue inside Captain — the same
retry/backoff spirit ADR-0001 already asked for, extended to cover
ordering, not just failure retries.

## Alternatives considered

- **BioHunter submits to the existing form trigger's URL programmatically**
  — rejected: brittle against HTML form structure, no clean JSON contract.
- **Pipeline POSTs a callback to a BioHunter-hosted endpoint when the run
  completes**, instead of Captain polling — rejected for now: BioHunter has
  no persistent server process (it's a single-user CLI/cron tool), so this
  would mean standing up an HTTP listener solely to receive this callback.
  Revisit if BioHunter grows a persistent daemon anyway (e.g. for Filler's
  dashboard).
- **Return resume/cover-letter content directly in the final HTTP
  response** instead of reading files off disk — rejected: incompatible
  with an indeterminate-length human-approval pause sitting in the middle
  of the request, and it's strictly more n8n-side rework than reusing the
  file-writing behavior the pipeline already has.
- **Fire all Writer calls immediately and let them queue at the paused
  `Wait (Form)` node itself** — rejected: undocumented/unclear how n8n
  behaves when multiple concurrent executions hit the same paused form
  (ADR-0004's own open question). Better to make ordering explicit and
  deterministic in Captain, which is already the coordination layer.

## Consequences

- **n8n-side change required, not zero-code:** the Webhook node's
  immediate response must pass through `posting_id`, and it needs to be
  threaded through `split jobs` → `assemble draft resume` → the final
  Code node so output files can be named/located predictably (e.g.
  `/data/final/{posting_id}_resume.md`) instead of relying on
  company/title-based naming that could collide across postings.
- Captain needs an n8n API key to poll `/api/v1/executions/{id}` — a new
  credential to add to `.env.example`, already covered by the
  `gitleaks`/pre-commit setup from ADR-0002.
- BioHunter and the n8n pipeline sharing a filesystem path is now a load-
  bearing assumption, not just a convenience — if the pipeline ever moves
  off this host, this ADR's contract needs revisiting (the callback
  alternative above becomes the likely replacement at that point).
- ROADMAP Phase 2's three "decide X" checklist items (from ADR-0004) can
  be marked resolved and replaced with concrete implementation subtasks
  derived from this ADR — see suggested diff below.
- The cover-letter-LLM-call question from ROADMAP Phase 2 is still open
  and unrelated to this ADR: the pipeline already produces the cover
  letter itself, so that BioHunter-side task is likely redundant, but
  confirming that is a separate decision, not resolved here.

## Suggested `ROADMAP.md` Phase 2 diff

```diff
- [ ] Decide trigger shape — add/confirm an n8n Webhook trigger node (pipeline
      currently uses `On form submission`) (ADR-0004 #1)
- [ ] Decide webhook request/response contract — what BioHunter posts in vs.
      what the pipeline returns (section text vs. file paths vs. assembled
      cover letter pre/post stitch pass) (ADR-0004 #2)
- [ ] Design Captain's handling of the pipeline's per-execution (not
      per-item) human-approval Wait step before allowing concurrent Writer
      calls (ADR-0004 #3)
+ [x] Trigger shape, contract, and concurrency decided — see ADR-0005
+ [ ] n8n: add Webhook trigger node alongside existing form trigger
+ [ ] n8n: thread posting_id through split jobs → assemble draft resume →
      final file-writer Code node (needed for predictable output paths)
+ [ ] Captain: add pipeline_status field + single-in-flight queue logic
+ [ ] Captain: n8n execution-polling client (GET /api/v1/executions/{id})
+ [ ] Add n8n API key to .env.example
  [ ] n8n webhook client for scoring
  [ ] n8n webhook client for resume assembly
```
