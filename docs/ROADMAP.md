# Roadmap

Mirror these phases as GitHub Issues with checkboxes so progress is visible outside this file too.

**Revised 2026-08-14** — this session was planning-only (no code), following
`2026-08-14_1_BioHunter-DeviationControl-ProgressNotify-RoadmapHandoff.md`.
Its job was to (a) turn that handoff's "not yet verified" list into an
explicit punch-list, and (b) organize a batch of new feature ideas into a
stable structure so future sessions don't each have to re-derive
architecture from scratch. See "Four dashboard subsystems" below — that's
the organizing idea this session produced, and it should be the first
thing a new AI session reads before touching `dashboard.py` or any related
file.

**Decisions made by inference this session, not explicit confirmation —
flag if wrong:**
- MVP = the current manual flow (Scout finds postings → Generate → review
  → download → apply yourself), once the verification punch-list below is
  actually confirmed live and the index-page bug is fixed. The remaining
  unchecked Phase 2 items (`awaiting_review` gate, score-threshold
  auto-trigger, static report, Job-fit Scorer) are explicitly **post-MVP**,
  deferred behind the four subsystems.
- The index-page Generate-button bug (Section 3 of the 2026-08-14 handoff)
  does **not** get its own fix — it's subsumed by Captain's job-queue
  rebuild below. A standalone patch would be wasted work right before
  Captain replaces the whole in-flight-check mechanism it lives in.
- Concurrent-generation safety is resolved by policy, not investigation —
  Captain's batch feature already requires jobs to run one at a time
  (KV-cache safety on the M4), which makes "should we serialize?" moot
  regardless of what `llm.py` turns out to do under the hood. `llm.py`
  still hasn't been uploaded in this thread if that policy ever needs
  revisiting.

---

## MVP verification punch-list — do this before any new feature work

Per this project's own norm (verify real output, don't trust a description
of a change) — everything below shipped in the 2026-08-14 session as
code, but has only been exercised via syntax-checking, not a real run.
This is a checklist to click through, not a coding task:

- [ ] Candidate name/contact line actually appears in a downloaded PDF
- [ ] `strict` and `loose` stability settings visibly change output
      (only `balanced` has been run live)
- [ ] Inline `**bold**` renders correctly in the report/PDF
- [ ] New word-diff rendering in Revision History looks right (no visual
      before/after was ever reviewed for this one)
- [ ] Dashboard-link footer/header shows up
- [ ] Browser notification fires + topbar indicator works on your actual
      browser/OS

---

## Four dashboard subsystems (new, 2026-08-14)

Everything touching `dashboard.py` going forward belongs to exactly one
of these. Naming them is the point — a session that says "I'm doing
Captain work" or "I'm doing Workspace work" should be able to load just
that section plus the relevant existing files, instead of re-reading the
whole handoff history.

### 1. Scout & ingestion
Three entry points into `postings`, one shared table:
- **ATS-adapter pipeline** (existing) — six known platforms, unchanged.
- **Guided company onboarding** (new) — replaces the vague "auto-generate
  an adapter" idea with a scoped, human-in-the-loop wizard:
  1. Static fingerprint scan (`detect_ats.py` — already built)
  2. Headless-browser scan for JS-rendered sites (`discover_ats.py`,
     scoped in ADR-0003, **not yet built** — this is the single highest-
     value, lowest-risk piece for hitting 100+ companies, since the
     companies most likely to be missing are smaller/newer biotechs
     running modern JS-heavy sites)
  3. For companies neither of those catches: a guided extraction wizard.
     You find the real request via DevTools (Network tab → Fetch/XHR →
     find the JSON response with job data) and paste the URL + a sample
     response in; the LLM proposes a field mapping (which JSON keys are
     title/location/description/url); BioHunter re-runs the actual
     request live and shows you real parsed postings before you approve.
     What gets saved is **a mapping (data), not generated code** — one
     hand-written, reviewed `CustomAPIAdapter` class interprets every
     company's mapping at runtime, so this never means writing and
     running fresh Python unattended. Sites with no clean JSON API fall
     back to the same wizard shape targeting CSS selectors instead,
     feeding the existing structured-scrape engine.
  - [ ] `discover_ats.py` (ADR-0003)
  - [ ] `CustomAPIAdapter` class + field-mapping config schema
  - [ ] Guided onboarding wizard UI (JSON-API path)
  - [ ] Guided onboarding wizard UI (CSS-selector path, reuses fallback
        scraper)
- **Browser extension capture** (new) — click-to-save the posting you're
  currently viewing (LinkedIn or any board), same `RawPosting` shape as
  everything else. Not automated LinkedIn scraping (against their ToS) —
  a manual, per-click capture of what's already rendered in your own
  logged-in session, same mechanism competitor tools like JobHunnt use.
  - [ ] Browser extension (capture button → POST to a manual-entry-style
        endpoint)
- **Target**: 100+ Bay Area biotech companies in the registry (up from
  8/10 target list today), enabled by the above rather than hand-editing
  `companies.yaml` one entry at a time.

### 2. Captain (job orchestration)
Named after the role your own original design doc specified and never
built. Currently every job type (`generate`, `score_batch`, `scout`,
`dead_link_check`) is a bespoke thread-spawning function in
`dashboard.py`, tracked in an in-memory `_jobs` dict that's lost on
restart. One rebuild fixes four things at once:
- [ ] Persisted job queue (DB table, not an in-memory dict) — job history
      survives a dashboard restart
- [ ] Multi-select batch generation — select several postings, run
      Generate sequentially, one at a time (avoids KV-cache blowup on the
      M4 24GB), with a real status bar across the whole batch
- [ ] Unified progress-bar contract every job type implements once,
      instead of `generate`'s real bar and separate bespoke pages for
      score/scout/dead-link jobs
- [ ] Combine "Run Scout" and "check for dead links" into one job
- [ ] Job history becomes a permanent page backed by the persisted queue
      (not "only jobs from this browser session")
- [ ] Supersedes the index-page Generate-button bug — a correct in-flight
      check falls out of this rebuild, no separate patch needed

### 3. Workspace (presentation layer)
Reads postings/drafts/jobs, knows nothing about LLMs or ATS adapters.
Key architectural point: **one shared, filtered/sorted data layer, three
interchangeable layout renderers** — not three separate queries. A
"gallery of drafted postings" (originally a separate feature idea) turns
out to just be a `has_draft` filter + `final_score` sort on that shared
layer, exposed differently per layout rather than built as a fourth page.
- [ ] Extend `_filtered_postings()` with `has_draft` filter + score sort
- [ ] `dashboard_settings` singleton row (layout mode, color palette,
      dark/light) — same dashboard-editable pattern as
      `candidate_settings`, kept as a separate table (one module, one
      concern)
- [ ] Ten named CSS-variable palettes (5 light, 5 dark) — `_DASHBOARD_STYLE`
      already uses `var(--ink)`/`var(--panel)`/etc., so this is filling in
      value sets, not restructuring CSS
- [ ] Stable topbar nav (Postings / Jobs / Settings) sitting above
      whichever layout is active, replacing today's scattered per-page links
- [ ] Layout 1 — **Master-detail split** (build first: doubles as the
      drafts gallery with the least new UI)
- [ ] Layout 2 — **Data-dense table** with slide-over drawer (best fit
      for sorting/comparing drafts by score)
- [ ] Layout 3 — **Kanban board**, columns = `posting.status`
      (new/scored/applied/rejected/stale), has-draft shown as a card badge
      rather than a column
- Build order matters here: shared data layer + settings row first, then
  ship *one* layout fully before starting the other two — building all
  three at once is how this becomes a half-finished mess in every one.

### 4. Writer / export
No longer just an export format question — this subsystem now owns the
whole post-generation workflow. **Old workflow:** generate → download
DOCX → edit in Pages → re-export PDF → submit. **New workflow:**
generate → edit in-dashboard → optional local-LLM proofread pass →
export PDF → submit. DOCX doesn't disappear, it just changes role — no
longer a required step, still there if you ever want to edit outside
BioHunter.

- [ ] `resume_docx.py`, mirroring `resume_pdf.py`'s structure: reuses
      `report.py`'s shared markdown-parsing helpers
      (`_split_headed_sections`, `_render_prose_block`), swaps the
      rendering backend from HTML+Playwright to `python-docx`. New
      dependency: `pip install python-docx`. DOCX chosen over RTF for
      fidelity in Pages/LibreOffice.
- [ ] Two new routes: `posting_resume_docx`, `posting_cover_letter_docx`,
      mirroring the existing PDF routes
- [ ] Candidate signature image: new `candidate_settings` field
      (`signature_path`), uploaded once via Settings, stored on disk,
      embedded in both the PDF (`<img>`, base64) and DOCX
      (`add_picture()`) cover letter templates between "Sincerely," and
      the typed name — omitted if not set, same convention as
      name/contact line today
- [ ] **In-dashboard editor.** A new mutable row per posting (e.g.
      `final_edit`) — separate from `drafts_db.py`'s `DraftRecord` rows,
      which stay immutable AI-generation snapshots so `diff.py`'s
      round-to-round comparison is never affected by hand edits. Seeded
      from the latest draft's `tailored_summary`/`tailored_bullets`/
      `cover_letter` the first time you click Edit. Plain textareas per
      section — content is already markdown-shaped, no rich editor
      needed. A "reset to AI draft" button discards the edit.
- [ ] **Regenerate-while-editing handling.** If you regenerate after
      starting an edit, the in-progress edit is archived into the
      version list below (labeled "your edit, before regenerating"), not
      silently discarded and not silently kept — named explicitly per
      this project's own norm of calling out real behavior changes.
- [ ] **Local-LLM proofreader.** Per-section, not whole-document (keeps
      each call small and fast on the M4). Sends just that section's
      current edited text to a local Ollama model with a narrow
      instruction — smooth grammar/phrasing, don't add or remove
      substance. Never applies silently: shows a diff (reusing the
      word-level diff view already built for Revision History this
      session), you accept or discard per suggestion. Same
      propose-then-approve pattern as Filler/the ATS-adapter wizard.
- [ ] **Version history panel**, collapsible per entry (plain HTML
      `<details>`/`<summary>`, no JS framework needed — matches the
      dashboard's existing plain-Flask approach). Two layers, flattened
      into one chronological list: revision rounds within a generation
      run (already in `RevisionResult`) and separate generation runs
      across regenerations (needs a new `list_drafts_for_posting(conn,
      posting_id)` in `drafts_db.py` — today only `get_latest_draft()`
      exists). Collapsed shows timestamp/round/score; expanded shows
      that version's content, read-only, for reference/inspiration only
      — never selectable as "the" active version. Includes archived
      pre-regenerate edits (above). Scope decision: **generation history
      only, not rejected proofreader suggestions** — those are usually
      rejected because they were wrong, not because they're worth
      revisiting, so excluding them keeps the list from getting
      cluttered.
- [ ] Preview + PDF export both read from the edited content when a
      `final_edit` row exists (falling back to the latest AI draft
      otherwise), reusing `render_resume_html`/`render_cover_letter_html`
      unchanged — same rendering function, new content source. Preview
      route returns raw HTML; export route pipes the same HTML through
      `html_to_pdf_bytes()`.

---

## Phase 1 — Scout + storage — code-complete, registry in progress; see docs/handoffs/2026-07-29-*.md
- [x] Turso (libSQL) schema — built, includes `run_log` and posting status lifecycle (new/scored/applied/rejected/stale); still running local SQLite, Turso env vars supported but not yet switched on
- [~] Company registry (`config/companies.yaml`) — 8/10 target companies confirmed live (Genentech, Gilead, Denali, Astellas, BioMarin, Amgen, Guardant Health, Mammoth Biosciences, Nurix Therapeutics — 317 postings, 0 errors); 2 remain blocked (Exelixis, Scribe Therapeutics); **superseded by the Scout & ingestion subsystem above** — 100+ company target now depends on `discover_ats.py` + the guided onboarding wizard, not one-by-one manual `companies.yaml` edits
- [x] ATS API adapters — six: Greenhouse, Lever, Ashby, Workday (multi-site support), Jobvite (HTML scrape, pagination gap noted), Jobsyn/NLX (federal-contractor pattern)
- [x] Fallback scraper + diff detection — built; JS-rendered sites still need DevTools-network-tab technique or `discover_ats.py`
- [x] Rate-limiting / robots.txt respect — built
- [x] Stale-posting detection — postings unseen for 30 days marked `stale`, excluded from `list-postings` by default; `applied`/`rejected` postings protected
- [ ] `discover_ats.py` — see Scout & ingestion subsystem above
- [ ] Jobvite pagination fix ("Show More" not followed — large categories may undercount)
- [ ] `--profile` flag for concurrent multi-search — still open, low priority

## Phase 2 — Writer + Critic (native pipeline)
**Superseded architecture note:** this section originally tracked integration
decisions for calling the n8n + Hermes pipeline over a webhook (n8n confirmed
production-ready as of 2026-08-04, ADR-0004). ADR-0006 (2026-08-05) retired
n8n from BioHunter's runtime path entirely and ported its logic natively
into Writer/Critic instead — see that ADR for the full reasoning; the n8n
workflow itself is kept as a reference implementation, not deleted.

- [x] Native pipeline port — Qdrant retrieval + all 8 selection branches
      (resume: summary/headings/bullets/skills; cover letter:
      intro/story/impact/gratitude) + cover-letter stitch pass —
      `src/biohunter/writer.py`, `selection.py`, `qdrant.py`
- [x] Critic step — one blind-review LLM call over a completed draft —
      `src/biohunter/critic.py`. Currently routed to local Ollama rather
      than Anthropic (no ongoing Anthropic API access right now)
- [x] Revision loop — Writer → Critic → revise → critique —
      `src/biohunter/revision.py`
- [x] Resume Diff — unified diff between any two rounds' output —
      `src/biohunter/diff.py`
- [x] Display-only ATS Score on Critic's output — deliberately not wired
      to any auto-stop/plateau logic (scope decision, see ADR-0006)
- [x] Candidate settings + PDF header wiring (2026-08-14) — `settings_db.py`,
      wired into both PDF export routes
- [x] Deviation/stability control (2026-08-14) — `strict`/`balanced`/`loose`
      threaded through `selection.py`, `writer.py`, `revision.py`
- [x] Report/PDF rendering fixes (2026-08-14) — dashboard link, inline
      markdown, word-level diff for prose sections
- [x] Real progress bar + cross-page notification (2026-08-14) — see
      Captain subsystem above for where this evolves next
- [ ] `awaiting_review` posting status + human-approval gate — **post-MVP**,
      deferred behind the four subsystems (see decisions at top)
- [ ] Score-threshold config + Captain auto-trigger for Writer — **post-MVP**,
      explicitly deferred until the gate above exists
- [ ] `biohunter report` — static HTML activity report — **post-MVP**
- [ ] Job-fit Scorer — ranks postings before Writer runs — **post-MVP**
- [ ] Lightweight weekly cloud token/cost log (ADR-0002) — low urgency
      while running local-only

## Phase 3 — Analyst weekly report
- [ ] Query layer: new postings, application status, outreach status
- [ ] Conference watchlist (start as a maintained static list)
- [ ] Report formatting + delivery (email or Telegram)

## Phase 4 — Filler
- [ ] Playwright setup
- [ ] Field-mapping for the 1-2 most common ATS platforms among target companies
- [ ] Human-approval gate (no auto-submit)
- [ ] Per-company form fingerprint caching

## Phase 5 — Networker
- [ ] Manual contact CSV import (start here before automating discovery)
- [ ] Email pattern inference + confidence scoring
- [ ] Draft-only outreach email generation
- [ ] Follow-up tracking surfaced in weekly report

## Interface note (not yet a phase)
- Superseded in part by the Workspace subsystem's topbar decision above —
  a Telegram bot as the approval channel for Filler/Networker gates is
  still worth considering once those phases are actually being built, but
  the dashboard itself is no longer in question now that Workspace has a
  concrete design (see ADR-0002 for the original framing).
