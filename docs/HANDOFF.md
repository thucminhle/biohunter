# Handoff — Starting a New AI Session

Use this doc to start any new chat/session on this project (Claude, Claude Code, etc.)
without re-explaining everything from scratch. Update the "Current state" section
at the end of each work session.

## Copy-paste prompt for a new chat

**Note: the repo is PRIVATE, so a new claude.ai chat cannot fetch it from the
URL — web_fetch only works on public URLs.** Instead, attach these files
directly to your first message (paperclip/attach in the chat UI):
- The latest dated file in `docs/handoffs/` (most important — has current state)
- `docs/FILE_TREE.txt` (so the new chat can see what already exists before writing anything)
- `docs/ROADMAP.md`
- `docs/adr/0001-*.md` and `docs/adr/0002-*.md`

Then paste this prompt:

```
I'm building "BioHunter" — a self-hosted, multi-agent job-hunting system for
Bay Area biotech roles (Scout monitors company career pages directly, Scorer/
Writer delegate to my existing Hermes Agent + n8n pipeline, Filler auto-fills
application forms for my approval, Networker finds contacts and drafts
outreach, Analyst sends a weekly report — all human-approval-gated, no
auto-submit/auto-send).

I've attached my project's current handoff snapshot, file tree, roadmap,
and ADRs — please read them for full context before we continue.

My stack: VS Code, n8n, Docker, Turso (libSQL), Hermes Agent, Ollama/MLX/
OpenCode for local models, Claude for cloud calls. macOS (M4, 24GB RAM).

Working style: I want to learn to build this, not just receive finished
code. Walk me through development and testing step-by-step. Low-level/
teachable code — write it out and have me type/apply it myself with
guidance. Heavier implementation is fine for you to write directly, but
explain what it does. Treat this as mentorship for this app and future
ones, not just ticket completion.

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
- **Mentoring mode, not autopilot:** I want to learn to build apps, not just receive finished code. For actual feature development, walk me through it step-by-step — explain what we're building and why, then guide me through writing/testing it myself where the code is low-level/teachable. Heavy, complex implementation (e.g. a new ATS adapter's parsing logic) is fine for AI to write directly, but talk me through what it does rather than just handing it over silently. Treat this as mentorship for this app and for future ones, not just ticket completion.
- **Before sending code changes:** prefer a full-codebase sync over incremental patches for anything nontrivial — a partial-apply once caused a command to silently go missing for a while undetected (see `docs/handoffs/2026-07-29-*.md`). If sending an incremental patch anyway, tell me explicitly to run `git status`/diff right after applying it to confirm it landed fully.

## Current state

**Full detailed state lives in `docs/handoffs/` — read the most recent
dated file there first** (currently: `2026-07-29-phase1-registry-complete.md`).
This section just tracks the pointer + a one-line summary; don't duplicate
the detailed state here.

**Last updated:** 2026-07-29
**Current phase:** Phase 1 (Scout + storage) — code-complete, registry in
progress (5/10 target companies confirmed live, 505 postings tracked, 0
errors); Phase 2 not started.
**One-line summary:** Six ATS adapters now exist (Greenhouse, Lever,
Ashby, Workday-multi-site, Jobvite, Jobsyn/NLX for federal-contractor
companies); stale-posting detection added; 7 companies remain unresearched.
See the dated handoff file for full detail, known gaps, and exact next steps.

## When completing a phase or major feature

Ask the AI session that did the work to generate a fresh handoff prompt
(specific, detailed, includes exact file names/gaps/errors — not generic).
Then:
1. Save it as `docs/handoffs/YYYY-MM-DD-short-description.md`
2. Update the "Current state" section above to point to it
3. Regenerate `docs/FILE_TREE.txt` (`git ls-files > docs/FILE_TREE.txt`)
   so the next chat can see what already exists before writing anything
4. Attach the dated handoff + `docs/FILE_TREE.txt` (not the repo URL) to
   the new chat — see note above on why fetch-by-URL isn't reliable here

This keeps a permanent, dated history of exactly where the project stood
at each transition — same pattern as ADRs, but for state rather than
decisions.
