BioHunter — Phase 2 Development Handoff

Project Summary

BioHunter is a self-hosted, local-first AI platform that automates biotech job searching and application preparation.

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

The original implementation existed as a large n8n workflow.

The long-term goal is to migrate the entire pipeline into a maintainable Python codebase while preserving behavioral parity with the original workflow.

⸻

Current Status

Phase 1 — Native Writer

Status: Completed

The Writer has been successfully ported from n8n to Python.

Implemented:

* LLM abstraction
* Native Ollama support
* OpenAI-compatible support
* Anthropic support
* Role routing
* Qdrant retrieval
* Resume variant selection
* Heading selection
* Bullet selection
* Skills selection
* Intro selection
* Story selection
* Impact selection
* Gratitude selection
* Resume assembly
* Cover letter generation
* verify-llm CLI
* verify-writer CLI

The Writer now successfully generates both:

* tailored resume
* tailored cover letter

without timing out.

⸻

Major Debugging Milestone

A lengthy parity-debugging session identified that the native implementation was not faithfully reproducing the n8n runtime behavior.

The bottleneck was not hardware.

It was behavioral differences between the Python implementation and the original n8n workflow.

The following changes restored parity.

⸻

Native Ollama client

A new

OllamaNativeClient

was implemented.

Native Ollama requests now use

/api/chat

instead of the OpenAI compatibility endpoint.

MLX/OpenAI compatibility remains unchanged.

⸻

roles.yaml

All Ollama provider URLs now point to

http://localhost:11434

instead of

http://localhost:11434/v1

Native routing determines the correct endpoint.

⸻

Thinking Mode

Every Writer branch now accepts

think: bool = False

including

* summary
* headings
* bullets
* skills
* intro
* story
* impact
* gratitude
* cover-letter stitch

matching the original n8n behavior.

⸻

Writer

generate_draft()

now propagates

think

uniformly to every branch.

This matches the original workflow where one UI toggle controlled the entire run.

⸻

CLI

verify-writer

now supports

--think

Default:

Fast mode

Optional:

--think

runs the entire pipeline with thinking enabled.

⸻

Performance Results

Fast mode

think = false

works reliably.

Thorough mode

think = true

is significantly slower but mirrors the original n8n behavior.

Example observed during parity testing:

Skills selection
think=false
≈25 seconds
think=true
≈144 seconds

This is expected.

⸻

Current Priority

The Writer is considered feature-complete for Phase 1.

The focus should now shift toward building the remainder of BioHunter rather than continuing to optimize the Writer unless new bugs are discovered.

⸻

Phase 2 Objectives

Development priority should be:

1. Critic Agent (Highest Priority)

Implement the Critic.

Input:

* generated resume
* generated cover letter
* job description

Responsibilities:

* ATS evaluation
* recruiter critique
* missing keywords
* unsupported claims
* weak bullets
* weak summary
* cover letter critique

Output:

structured feedback suitable for revision.

⸻

2. Revision Loop

Create an automatic revision workflow.

Writer
↓
Critic
↓
Writer Revision
↓
Critic
↓
Human Review

Support configurable revision rounds.

Example:

revision_rounds: 2

⸻

3. Resume Diff

Generate a report showing

* original resume
* tailored resume

highlighting

* inserted content
* removed content
* rewritten bullets

This should make human review significantly easier.

⸻

4. ATS Score

Estimate

* ATS compatibility
* keyword coverage
* role alignment

Provide category scores.

⸻

5. Static HTML Report

Generate a polished HTML report containing

* tailored resume
* tailored cover letter
* critic report
* ATS score
* revision history
* diff report

This replaces the current CLI-only output.

⸻

6. Scout

Resume development of the Scout.

Capabilities:

* scrape biotech career pages
* identify new openings
* normalize postings
* store locally

⸻

7. Scorer

Implement job ranking.

Factors include

* scientific fit
* location
* seniority
* visa compatibility
* salary (if available)
* user preferences

⸻

8. Local Knowledge Base

Expand Qdrant usage beyond resume fragments.

Potential collections:

* publications
* patents
* presentations
* research interests
* networking contacts
* institution profiles

⸻

Development Philosophy

Continue following these principles.

* Local-first whenever practical.
* Behavioral parity before optimization.
* Prefer small, verifiable commits.
* Preserve deterministic outputs where possible.
* Instrument before optimizing.
* Human approval remains the final step before application submission.

⸻

Recommended Files to Upload

Core

src/biohunter/llm.py
src/biohunter/writer.py
src/biohunter/selection.py
src/biohunter/qdrant.py
src/biohunter/cli.py
config/roles.yaml

Architecture

docs/adr/0006-native-pipeline-auto-writer-static-report.md
docs/FILE_TREE.txt

Reference

Resume_Tailoring_3.json
seed_qdrant.js

Latest handoff

2026-08-05-native-pipeline-port-step1-in-progress.md

⸻

Working Style

Continue the mentoring style used throughout this project.

When proposing architecture or implementation changes:

* explain the rationale before coding,
* preserve parity with the existing Writer where appropriate,
* avoid unnecessary abstractions,
* favor incremental, testable milestones over large rewrites.

If a proposed change would intentionally diverge from the original n8n behavior, clearly identify it as a design improvement rather than a parity fix.

⸻

One suggestion on priorities

Given everything you’ve built, I would make one adjustment to the roadmap before moving on to Scout and Scorer: implement the Critic and revision loop first. Those components immediately increase the quality of every application your system generates and build directly on the Writer you’ve just stabilized. Once that feedback loop is in place, expanding Scout and Scorer becomes much more valuable because every discovered opportunity can flow through a complete draft → critique → revision → review pipeline.
