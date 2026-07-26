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

## Current state (update this each session)

**Last updated:** 2026-07-26
**Current phase:** Phase 1 — Scout + storage (not yet started)
**Repo status:** Scaffold complete (README, ADRs 0001-0002, ROADMAP, config/roles.yaml,
pre-commit secrets scanning). No application code yet.
**Next concrete step:** Turso schema (companies/postings/applications/contacts/
outreach_emails/conferences tables) + company registry + pick which ATS platforms
(Greenhouse/Lever/Ashby) your target companies actually use.

## Habit going forward

At the end of each work session (or before closing a long chat), spend 2 minutes:
1. Update "Current state" above
2. Add a CHANGELOG.md entry for anything shipped
3. Commit + push

This keeps every future session — yours or a fresh AI chat's — able to pick up
exactly where you left off by reading four files, not scrolling through history.
