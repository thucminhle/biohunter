# Handoff — Starting a New AI Session

Use this doc to start any new chat/session on this project (Claude, Claude Code, etc.)
without re-explaining everything from scratch. Update the "Current state" section
at the end of each work session.

## Copy-paste prompt for a new chat

**Note: the repo is PRIVATE, so a new claude.ai chat cannot fetch it from the
URL — web_fetch only works on public URLs.** Instead, attach these files
directly to your first message (paperclip/attach in the chat UI):
- README.md
- docs/design/biotech-job-hunter-design.md
- docs/ROADMAP.md
- docs/adr/0001-thin-wrapper-around-n8n-hermes.md
- docs/adr/0002-adopt-patterns-from-jht.md
- CHANGELOG.md

Then paste this prompt:

```
I'm building "BioHunter" — a self-hosted, multi-agent job-hunting system for
Bay Area biotech roles (Scout monitors company career pages directly, Scorer/
Writer delegate to my existing Hermes Agent + n8n pipeline, Filler auto-fills
application forms for my approval, Networker finds contacts and drafts
outreach, Analyst sends a weekly report — all human-approval-gated, no
auto-submit/auto-send).

I've attached my project's docs (README, design doc, roadmap, ADRs,
changelog) — please read them for full context before we continue.

My stack: VS Code, n8n, Docker, Turso (libSQL), Hermes Agent, Ollama/MLX/
OpenCode for local models, Claude for cloud calls. macOS (M4, 24GB RAM).

I want to start/continue: <DESCRIBE THE SPECIFIC TASK>
```

**Alternative for future sessions:** consider using Claude Code instead of
claude.ai chat for hands-on build work — it reads local files directly from
disk with no upload/fetch step at all, which will matter more once there's
actual application code to work on.

## Working with me

- Comfortable with architecture/design decisions — no need to over-explain the "why," I'm usually the one asking for it.
- Still building git/terminal fluency — give explicit step-by-step commands with expected output, one command at a time when troubleshooting rather than multi-line blocks.
- I paste back exact terminal output, so use that to diagnose precisely rather than guessing.
- Prefer file-based deliverables (single named file, not zipped folders) when the change is small — avoids nesting mistakes when copying into the repo.

## Current state

**Full detailed state lives in `docs/handoffs/` — read the most recent
dated file there first** (currently: `2026-07-26-phase1-scout-complete.md`).
This section just tracks the pointer + a one-line summary; don't duplicate
the detailed state here.

**Last updated:** 2026-07-26
**Current phase:** Phase 1 (Scout + storage) — mostly complete; Phase 2 not started
**One-line summary:** Scout works end-to-end for Workday-based companies
(Genentech, Gilead confirmed live); ATS adapters exist for Greenhouse/
Lever/Ashby/Workday; 8 of 10 target companies still need registry work;
Denali Therapeutics is the active blocker. See the dated handoff file for
full detail, known gaps, and exact next steps.

## When completing a phase or major feature

Ask the AI session that did the work to generate a fresh handoff prompt
(specific, detailed, includes exact file names/gaps/errors — not generic).
Save it as `docs/handoffs/YYYY-MM-DD-short-description.md`, then update
the "Current state" section above to point to it. This keeps a permanent,
dated history of exactly where the project stood at each transition —
same pattern as ADRs, but for state rather than decisions.
