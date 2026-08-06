Implementation is largely complete. The project is now in the parity verification and performance debugging phase.

Here’s the handoff I would use.

⸻

Native Resume/Cover-Letter Pipeline — Step 1 Runtime Verification & Parity Debugging — Handoff

Paste this entire document as the first message in a new chat.

⸻

Project summary

BioHunter is a self-hosted, multi-agent job hunting platform.

Pipeline:

Scout
    ↓
Scorer
    ↓
Writer
    ↓
Critic (future)
    ↓
Human Review

The Writer replaces an older n8n resume/cover-letter pipeline.

The implementation phase is largely complete.

This session is NOT about implementing additional functionality.

This session is about:

1. verifying parity with the original n8n workflow
2. diagnosing severe runtime/performance issues
3. ensuring the native implementation faithfully reproduces the n8n behavior before any optimization work begins.

⸻

Current state

Step 0 — LLMClient

Completed.

Implemented:

* LLMClient
* OpenAI-compatible backend
* Anthropic backend
* role routing
* model overrides
* verify-llm CLI

Verified.

⸻

Step 1 — Writer

Implemented.

Current implementation includes:

* Qdrant retrieval
* summary selection
* heading selection
* bullet selection
* skills selection
* intro selection
* story selection
* impact selection
* gratitude selection
* always-full section retrieval
* cover-letter stitch
* draft resume assembly
* verify-writer CLI

The implementation now needs runtime verification.

⸻

Current problem

The pipeline does not finish reliably despite the original n8n workflow completing successfully.

Originally

gemma4:12b-mlx

was used.

This produced:

* ReadTimeout
* RemoteDisconnected

during the Writer pipeline.

To eliminate Gemma-specific issues I switched the Writer role to

qwen3.5:4b-mlx

Current behavior:

The pipeline no longer crashes immediately.

However it is extremely slow.

Example:

select_skills()
↓
ReadTimeout (300 seconds)

even after increasing the HTTP timeout.

⸻

Important observation

The original n8n workflow

using

gemma4:12b-mlx

on

the SAME

* MacBook Air M4
* 24 GB RAM
* Ollama server
* Qdrant database
* job description
* resume catalog

completes in roughly

5 minutes

This strongly suggests the issue is NOT

* insufficient RAM
* Ollama
* Gemma
* model size

Instead it suggests the native Python implementation is not yet behaviorally identical to the n8n workflow.

Treat the n8n implementation as the reference (“gold standard”).

⸻

Current hypothesis

The most likely issue is parity, not hardware.

Possible causes include:

* prompt inflation
* incorrect Qdrant retrieval
* duplicated prompt assembly
* incorrect prompt formatting
* different model parameters
* different thinking mode
* different number of LLM calls
* accidental retries
* incorrect filtering

Do NOT assume the model is the bottleneck until parity has been verified.

⸻

Primary objective of this session

Determine why the Python Writer is substantially slower than the original n8n pipeline despite calling the same local Ollama server.

The goal is measurement before optimization.

⸻

Requested work

Please help investigate systematically.

I do NOT want immediate prompt rewrites.

I do NOT want model recommendations.

I do NOT want cloud model suggestions.

Instead:

1. Compare the native Writer to the n8n workflow

For every LLM stage compare

* prompt contents
* prompt size
* model parameters
* thinking flag
* streaming
* temperature
* response format
* number of Qdrant records
* number of LLM calls

Identify any behavioral differences.

⸻

2. Add instrumentation

Before changing anything else, add logging around every LLM call.

For each stage report

Stage
Model
Elapsed time
Prompt characters
Estimated tokens
Completion characters
Qdrant records retrieved

Example:

========================
Stage: Skills
Model:
qwen3.5:4b-mlx
Qdrant records:
18
Prompt chars:
13,482
Estimated tokens:
3,300
Completion chars:
240
Elapsed:
8.2 s
========================

This instrumentation should make the bottleneck immediately visible.

⸻

3. Inspect prompt construction

Look for

* duplicated catalogs
* duplicated job descriptions
* duplicated resume sections
* incorrect concatenation
* unexpectedly large prompts

Verify prompt construction matches the n8n workflow.

⸻

4. Inspect Qdrant retrieval

Confirm every retrieval function returns exactly what the corresponding n8n node retrieved.

Look for

* missing filters
* incorrect section types
* oversized catalogs
* duplicated payloads

⸻

5. Verify model request parity

Compare

Python request

vs

n8n request

Specifically verify

* endpoint
* JSON payload
* think parameter
* stream parameter
* response format

If they differ, explain why.

⸻

Please avoid

Until parity has been verified

please avoid

* changing prompts
* changing models
* increasing timeout further
* recommending Anthropic/OpenAI

The implementation should first behave like the n8n workflow.

⸻

Working style

Continue the previous mentoring style.

Walk through debugging one step at a time.

Prefer measurement over guessing.

Use the existing n8n workflow as the reference implementation.

Treat any behavioral difference between Python and n8n as a potential bug until proven otherwise.

⸻

Files to upload

Required

docs/handoffs/2026-08-05-native-pipeline-port-step1-in-progress.md
Resume_Tailoring_3.json

(the original n8n workflow)

config/roles.yaml
src/biohunter/llm.py
src/biohunter/qdrant.py
src/biohunter/selection.py
src/biohunter/writer.py
src/biohunter/cli.py

Recommended

docs/adr/0006-native-pipeline-auto-writer-static-report.md
docs/handoffs/2026-08-04-resume-pipeline-e2e-complete.md
seed_qdrant.js
docs/FILE_TREE.txt

⸻

One additional suggestion: after the AI has reviewed the code, ask it to produce a side-by-side parity table comparing each n8n node to its Python equivalent. For each stage, it should list the n8n node name, the corresponding Python function, the Qdrant query, the LLM prompt source, the expected input/output, and any behavioral differences it identifies. That kind of audit often reveals subtle discrepancies that are easy to miss when reading the code sequentially.
