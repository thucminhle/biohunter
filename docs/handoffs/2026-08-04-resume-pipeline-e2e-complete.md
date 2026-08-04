# n8n + Hermes Resume/Cover Letter Pipeline — Handoff (End-to-End Complete)

Paste this whole document as the first message in a new chat to continue work with full context.

---

## Project summary

This is the **n8n + Hermes Agent pipeline** referenced in BioHunter's
`docs/adr/0001-thin-wrapper-around-n8n-hermes.md`: an existing, standalone
workflow that takes a job description, retrieves matching resume + cover
letter content from Qdrant (verbatim selection only, no invention),
assembles a draft, scores it for ATS match, gets an LLM critique, pauses
for human approval via a form, then produces revised final resume + cover
letter as separate Markdown files on disk.

**This system is not part of the BioHunter codebase.** Per ADR-0001,
BioHunter's Scorer and Writer agents are designed to be thin wrappers that
POST to this pipeline via webhook rather than reimplementing scoring or
resume assembly — but that webhook integration is Phase 2 work and **has
not been started yet** (BioHunter is still in Phase 1: Scout + company
registry, per `docs/handoffs/2026-07-29-registry-8of10-adr3-drafted.md`
and `ROADMAP.md`). This handoff is scoped purely to the n8n/Hermes side,
which now runs cleanly end-to-end on its own.

## Status: fully working end-to-end, no known open bugs

Previous handoff (`Resume_Pipeline_Handoff_v3.md`) was written mid-debug on
one blocking error. That error is now resolved and root-caused (see below).
A full run — form submission → 8 parallel Qdrant/LLM selection branches →
draft assembly → ATS scoring → critique → human-approval form pause →
revised final resume + cover letter written to disk — completes
successfully.

## Architecture (unchanged from v3, confirmed still accurate)

```
[On form submission] → split jobs (parses company_name, job_title, job_description, think)
  ├─→ fetch summary catalog → format → select → parse summary selection
  ├─→ fetch heading catalog → format → select headings → parse heading selection
  │     → fetch bullets for headings → format bullet catalog → select bullets → parse bullet selection
  ├─→ fetch skills catalog → format → select → parse skills selection
  ├─→ fetch always-full sections → format always-full sections
  ├─→ fetch intro catalog → format → select intro → parse intro selection      ┐
  ├─→ fetch story catalog → format → select story → parse story selection      ├→ merge cover letter branches
  ├─→ fetch impact catalog → format → select impact → parse impact selection   │    → edit cover letter (light stitch pass)
  └─→ fetch gratitude catalog → format → select → parse gratitude selection    ┘    → parse cover letter edit
        (all 8 branches run in parallel off split jobs)
  → merge branches (5 inputs: summary/bullets/skills/always-full/cover-letter)
  → assemble draft resume         — pulls cover_letter from `parse cover letter edit`
  → parse sections → score ATS → parse ATS score → critique resume
  → build review packet           — Code node; assembles JD, draft, ATS, critique
                                     into review_markdown (also carries cover_letter through)
  → Code in JavaScript             — writes review_markdown to /data/reviews/... via
                                     fs.writeFileSync
  → Wait (Form) → revise draft → parse revised sections
  → Code in JavaScript1            — writes final RESUME + COVER_LETTER files to disk
```

Qdrant collection `resume_content` (768-dim, Cosine) holds everything —
resume sections plus cover letter sections. Seeded via `seed_qdrant.js`.
Last confirmed successful seed: 104 points upserted. No changes to this
layer this session.

## What was actually wrong (root cause, closing out v3's open item)

v3 flagged one error — `"Task execution aborted because runner became
unresponsive"` on the review-packet file-writer Code node — with resource
pressure from the 8-branch parallel design as the leading hypothesis.
**That hypothesis was wrong.** The real cause:

- **Ollama runs natively on the host (not in a Docker container)**, while
  n8n runs inside Docker Desktop's Linux VM (LinuxKit, on Mac). Docker
  Desktop's VM is itself a resource-hungry process competing with Ollama
  for the same physical host CPU cores — there's no container-level
  isolation protecting one from the other.
- `docker stats n8n` only reports the n8n container's own cgroup usage. It
  showed the container idle (0.04–0.17% CPU, ~494MB/7.75GB memory) *during
  active failures*, which ruled out in-container resource pressure — but
  gave no visibility into host-level or VM-level contention.
- During heavy/parallel Ollama inference (all 8 branches calling Ollama
  concurrently), the host's CPU is saturated enough that Docker Desktop's
  VM scheduling degrades — n8n's task runner process can't get scheduled
  promptly enough to send heartbeats or accept task handoffs in time. This
  produced two different-looking errors depending on timing:
  - *"runner became unresponsive"* — a task started, then the runner
    missed its heartbeat window mid-execution.
  - *"task request timed out... not matched to a runner"* — a task was
    never picked up because the runner wasn't responsive when the request
    came in. (Confirmed on the unrelated, trivial `split jobs` node —
    proof this was never about any specific node's code or workload, since
    `split jobs` is the very first node in the graph, runs before any LLM
    calls, and is pure synchronous string/regex logic.)
- Every request from n8n to native Ollama also crosses Docker's
  `host.docker.internal` boundary through the vpnkit networking layer,
  which is a known fragile point under concurrent connection load on Mac
  — a secondary contributor to the same symptom.

**Fix that actually worked:** full Docker Desktop quit-and-restart (not
just `docker restart n8n` / container-level restart). This matters because
the degradation lives in the VM's internal state (scheduling backlog,
stuck runner subprocess, degraded vpnkit routing) — restarting the n8n
container just restarts a process inside an already-strained VM and
doesn't clear any of that. A full Docker Desktop restart tears down and
recreates the VM from scratch.

**If this recurs:** cross-reference `docker stats` (all containers, not
just n8n) against host-level CPU (Activity Monitor, since Ollama is
native) during a run, rather than assuming it's workflow/node-specific.
Raising `N8N_RUNNERS_HEARTBEAT_INTERVAL` and `N8N_RUNNERS_TASK_REQUEST_TIMEOUT`
may buy headroom but won't fix host-level VM contention — treat those as
mitigations, not the actual fix, if the symptom returns.

## Known gotchas (carried over from v3, still valid — do not re-litigate)

1. n8n's built-in "Read/Write Files from Disk" node is unreliable on
   Docker Desktop Mac bind mounts — worked around via Code node +
   `fs.writeFileSync` (`NODE_FUNCTION_ALLOW_BUILTIN=fs` required and set).
2. Code node "Run Once for Each Item" mode needs `return { json: {...} }`,
   a bare object, not an array.
3. Any regex/JSON parsing must match the LLM's actual output format
   exactly.
4. The Wait (Form) node pauses the whole execution, not per item — known
   limitation, out of scope, do not fix as a side effect.
5. Docker Desktop can get containers stuck in an unkillable state after
   task-runner crashes — `docker kill` → `docker rm -f` → restart Docker
   Desktop → `docker start n8n`. **Now understood as one symptom of the
   broader host/VM-contention issue above, not an unrelated quirk.**
6. Qdrant collection is `resume_content`, confirmed via
   `curl http://localhost:6333/collections` — not `resume_components`.
7. Exact-string matching between LLM selection output and catalog labels
   always needs a logged warning + fallback-to-first-entry, never a
   silent drop — implemented in every `parse * selection` node (8 total).
8. The `assemble draft resume` Code node was previously missing its
   `return` statement — already fixed; confirm it's still present if
   diffing against an older export.
9. **New this session:** treat "runner unresponsive"-class errors as a
   host-resource-contention signal first (see root cause above), not a
   workflow-complexity signal — the number of parallel branches was a red
   herring in this case.

## Working style

- Comfortable with Docker/n8n/CLI debugging — want exact commands/configs,
  not high-level pointers.
- Diagnose what's actually happening before proposing a fix.
- Running on a token/message-limited plan — ask only for the specific file
  excerpts or command output actually needed next, not full re-dumps.

## Where this fits in the bigger picture (BioHunter)

This pipeline is the system BioHunter's Scorer and Writer agents are
designed to call via webhook (ADR-0001) rather than reimplement. That
integration is **not built yet** — BioHunter is still finishing Phase 1
(company registry: 8/10 target companies live, Exelixis and Scribe
Therapeutics still need DevTools/discovery-tool resolution per ADR-0003).

**Now that this pipeline runs reliably end-to-end, the concrete Phase 2
prerequisites it unblocks are:**
1. Exposing this workflow's entry point as a proper n8n **webhook**
   (currently triggered via `On form submission` — needs a webhook trigger
   node added/confirmed, or the form-submission trigger needs to be
   callable programmatically from BioHunter's `Writer` agent).
2. Deciding what the webhook contract looks like — what BioHunter posts in
   (posting title/description/company at minimum) and what it gets back
   (resume sections? file paths? the assembled cover letter text before or
   after the "edit cover letter" stitch pass?).
3. ADR-0001's stated mitigation — "Captain should retry with backoff and
   flag stalled postings rather than fail silently" — should account for
   this pipeline's now-understood failure mode (host resource contention
   under concurrent Ollama load), not just generic n8n-down scenarios.
4. The `Wait (Form)` human-approval step (gotcha #4) pauses the *entire*
   execution, not per-item — this has direct implications for how
   BioHunter's Writer/Captain would need to handle concurrent postings if
   multiple are being scored/written at once; worth resolving before
   Phase 2 webhook work starts in earnest, not discovered mid-integration.

None of the above is started. This handoff exists so the next session
has an accurate, closed picture of the pipeline's current state before
Phase 2 webhook integration work begins.

## Files to attach to your first message in the new session

1. **This document** — current pipeline state, root cause of the resolved
   error, and what Phase 2 integration will need to decide.
2. **`docs/adr/0001-thin-wrapper-around-n8n-hermes.md`** — the BioHunter
   ADR this pipeline serves; defines the webhook boundary/contract intent.
3. **Latest n8n workflow export** (Workflow menu → Download) — full
   8-branch design, validated end-to-end.
4. **`seed_qdrant.js`** — current version, `resume_content` collection
   confirmed correct.
5. If picking up Phase 2 webhook work specifically: BioHunter's
   `docs/handoffs/2026-07-29-registry-8of10-adr3-drafted.md` (current
   BioHunter state) and `ROADMAP.md` (Phase 2 task list), so the new
   session has both sides of the integration in view at once.

---
*(End of handoff — paste everything above this line into a new chat.)*
