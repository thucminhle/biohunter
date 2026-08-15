# BioHunter — Planning Session: Four Dashboard Subsystems Defined; Scout & Ingestion Up Next

**Session date:** 2026-08-14 (second doc today; continues directly from
`2026-08-14_1_BioHunter-DeviationControl-ProgressNotify-RoadmapHandoff.md`,
which asked for a planning-only session to revise `docs/ROADMAP.md`).

**Why this doc exists:** this session was 100% planning, no code. It
produced a full revision of `docs/ROADMAP.md`, organized around four new
dashboard subsystems (Scout & ingestion, Captain, Workspace, Writer/
export). **The next session should build Scout & ingestion only** —
Captain, Workspace, and Writer/export are designed but deliberately not
in scope yet, to keep sessions small and self-contained per explicit
user request. This doc's job is to hand over just enough context to
start that one subsystem cleanly.

---

## 1. What happened this session

No code was touched. The session:
1. Read the prior handoff, the existing roadmap, the design doc, and the
   AST outline.
2. Grouped a batch of 8 new feature ideas the user brought into four
   named subsystems (see `docs/ROADMAP.md`'s "Four dashboard subsystems"
   section for the full breakdown — don't duplicate that reasoning here,
   just read it there).
3. Designed each subsystem in real depth, one at a time, with the user
   confirming each before moving on.
4. Wrote the full revised `docs/ROADMAP.md`, which **replaces** the old
   one (carries forward every `[x]`, restructures the rest).

**Explicit user instruction that should carry forward:** small,
self-contained sessions, one subsystem at a time. Don't let a Scout &
ingestion session drift into Captain/Workspace/Writer-export work even
if it seems related or convenient.

---

## 2. Scout & ingestion — what's actually being built next

Full design lives in `docs/ROADMAP.md`. Summary for orientation:

Three entry points into the `postings` table:
1. **ATS-adapter pipeline** (existing, unchanged) — six known platforms.
2. **Guided company onboarding** (new, the main build) —
   - `discover_ats.py`: headless-Playwright ATS discovery for JS-rendered
     career pages, per ADR-0003. `detect_ats.py` already does static-HTML
     fingerprinting for the same six platforms; this extends the same
     idea to sites that don't expose the fingerprint until JS runs.
   - `CustomAPIAdapter`: one generic, hand-written, reviewed adapter
     class that interprets a per-company field-mapping config at
     runtime (JSON key → title/location/description/url). **This is the
     one architectural decision worth re-stating explicitly in case it
     gets second-guessed:** the LLM proposes the mapping (data), it
     never generates and runs a new adapter class per company (code).
     That's a deliberate choice, not an oversight — see the roadmap
     entry for the full reasoning if it's unclear why.
   - Guided wizard UI: user finds the real request via DevTools, pastes
     URL + sample response in, LLM proposes the mapping, BioHunter tests
     it live against the real site, user approves before it's saved.
     Two paths — JSON-API (the above) and CSS-selector (same wizard
     shape, targets the existing fallback structured scraper instead)
     for sites with no clean JSON endpoint.
3. **Browser extension capture** (new) — click-to-save the currently-
   viewed posting (LinkedIn or any board) into the same `RawPosting`
   shape. Manual, per-click, from the user's own logged-in session — not
   automated scraping, which would violate most boards' ToS.

**Priority order the user should probably be told again, since it's
easy to lose track of:** `discover_ats.py` first (most fully scoped,
highest value for the 100+ company target), then `CustomAPIAdapter` +
config schema, then the wizard UI that ties them together. Browser
extension is lowest priority of the three entry points — it's the least
scoped and least connected to the "100+ companies" goal specifically.

---

## 3. What's NOT in scope for the next session

Captain, Workspace, and Writer/export are all designed in
`docs/ROADMAP.md` with real depth (Writer/export especially — it grew a
whole in-dashboard editor + proofreader + version-history design across
several follow-up turns). None of it should be touched yet. If the next
session finds itself wanting a persisted job queue (Captain) to show
progress on a long-running `discover_ats.py` scan, that's a real
dependency worth flagging back to the user rather than quietly building
a mini version of Captain to unblock itself — better to surface the
conflict than let subsystem boundaries blur on the first session.

---

## 4. Standing open items, carried forward unchanged

Everything in the 2026-08-14 handoff's Section 4 (Scribe Therapeutics
Greenhouse 404, Lever dead-link detection, "Example Biotech Inc" stale
entry, `is_posted: false` filtering, `cli.py`'s lack of PDF/stability
wiring) is still exactly as open as it was. None of it blocks Scout &
ingestion work, but none of it's been resolved either.

The MVP verification punch-list from the same handoff (candidate name in
PDF, strict/loose stability, inline bold rendering, word-diff view,
dashboard-link footer, browser notifications) is also still unconfirmed
— this was meant to be clicked through by the user directly, not part of
a coding session, and there's no evidence it's happened yet.

---

## 5. Working style — unchanged, still a hard default

Vibe-coded: upload files to chat, AI edits them, user downloads and
drops complete files into the local repo via VS Code/Git. Every code
change handed back as a complete downloadable file — never a diff, never
a snippet. Explain rationale before coding. Check for existing logic
before building new. Verify actual output rather than trusting a
description of a change. Restart the dashboard process after any `.py`
edit. Keep sessions small and scoped to one subsystem — this is a new,
explicit instruction as of this session, not just a style preference.

---

## 6. Files to upload next session

**Must-have:**
- `docs/ROADMAP.md` (the revised version from this session)
- This handoff doc
- `schema.sql`
- `docs/AST_OUTLINE.md`

**Scout & ingestion specific:**
- `src/biohunter/detect_ats.py`
- `src/biohunter/ats/base.py` and `src/biohunter/ats/__init__.py`
- `config/companies.yaml` and `config/companies_input.yaml`
- `src/biohunter/scout/scraper.py`

Not needed for this session: anything Captain/Workspace/Writer-export
specific (`dashboard.py`'s job mechanism, `llm.py`, `writer.py`,
`revision.py`, `resume_pdf.py`, `settings_db.py`) — save those for their
own sessions.
