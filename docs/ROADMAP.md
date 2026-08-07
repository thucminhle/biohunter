# Roadmap

Mirror these phases as GitHub Issues with checkboxes so progress is visible outside this file too.

## Phase 1 — Scout + storage — code-complete, registry in progress; see docs/handoffs/2026-07-29-*.md
- [x] Turso (libSQL) schema — built, includes `run_log` and posting status lifecycle (new/scored/applied/rejected/stale); still running local SQLite, Turso env vars supported but not yet switched on
- [~] Company registry (`config/companies.yaml`) — 8/10 target companies confirmed live (Genentech, Gilead, Denali, Astellas, BioMarin, Amgen, Guardant Health, Mammoth Biosciences, Nurix Therapeutics — 317 postings, 0 errors); 2 remain blocked (Exelixis, Scribe Therapeutics — need DevTools check or `discover_ats.py` per ADR-0003); 10x Genomics identified as a 7th ATS platform (Eightfold.ai), also pending ADR-0003 work
- [x] ATS API adapters — six: Greenhouse, Lever, Ashby, Workday (multi-site support), Jobvite (HTML scrape, pagination gap noted), Jobsyn/NLX (federal-contractor pattern)
- [x] Fallback scraper + diff detection — built; JS-rendered sites still need DevTools-network-tab technique or `discover_ats.py`
- [x] Rate-limiting / robots.txt respect — built
- [x] Stale-posting detection — postings unseen for 30 days marked `stale`, excluded from `list-postings` by default; `applied`/`rejected` postings protected
- [ ] `discover_ats.py` — headless-Playwright ATS discovery tool per ADR-0003, not yet built
- [ ] Jobvite pagination fix ("Show More" not followed — large categories may undercount)
- [ ] `--profile` flag for concurrent multi-search — still open, low priority

## Phase 2 — Writer + Critic (native pipeline)
**Superseded architecture note:** this section originally tracked integration
decisions for calling the n8n + Hermes pipeline over a webhook (n8n confirmed
production-ready as of 2026-08-04, ADR-0004). ADR-0006 (2026-08-05) retired
n8n from BioHunter's runtime path entirely and ported its logic natively
into Writer/Critic instead — there is no second process to call, so the
webhook trigger/contract/Captain-Wait-step decisions, the separate n8n
webhook clients for scoring and resume assembly, and the standalone
"LLM call for cover letter" item below are no longer applicable and have
been removed from this list. ADR-0001 is marked Superseded and ADR-0005 is
marked moot by ADR-0006 — see that ADR for the full reasoning; the n8n
workflow itself is kept as a reference implementation, not deleted.

- [x] Native pipeline port — Qdrant retrieval + all 8 selection branches
      (resume: summary/headings/bullets/skills; cover letter:
      intro/story/impact/gratitude) + cover-letter stitch pass, called
      directly via `LLMClient` + Qdrant Python client against the existing
      `resume_content` collection — `src/biohunter/writer.py`,
      `selection.py`, `qdrant.py` (ADR-0006 build order step 1)
- [x] Critic step — one blind-review LLM call over a completed draft,
      organized under six fixed markdown headers, no shared context with
      Writer's own prompt — `src/biohunter/critic.py` (ADR-0006 build order
      step 2 / ADR-0002's originally-planned Critic step). Currently routed
      to local Ollama rather than Anthropic, since there's no ongoing
      Anthropic API access right now — revisit the cloud routing in
      `config/roles.yaml` once that changes (see 2026-08-07 handoffs)
- [x] Revision loop — Writer → Critic → revise → critique, configurable
      round count, full round-by-round history returned —
      `src/biohunter/revision.py`. Built as a natural extension once Critic
      existed; not explicitly called out in ADR-0006's original build order
- [x] Resume Diff — unified diff between any two rounds' output
      (summary/bullets/cover letter diffed separately, unchanged sections
      reported explicitly rather than omitted) — `src/biohunter/diff.py`
- [x] Display-only ATS Score on Critic's output — a structured `SCORE: n/10`
      line parsed out of the critique text. Deliberately **not** wired to
      any auto-stop/plateau logic — an explicit scope decision (LLM-judged
      scores aren't guaranteed monotonic; revisit only after watching real
      score behavior across more postings, and even then keep a hard
      max-rounds ceiling) — see the 2026-08-07 Diff-Score-BulletFix handoff
- [ ] `awaiting_review` posting status + human-approval gate (ADR-0006 build
      order step 3, replaces the old per-execution `Wait (Form)` design) —
      not yet built; Critic/revision are deliberately persistence-agnostic
      (no DB writes) specifically so this can be layered on without
      changing either
- [ ] Score-threshold config + Captain auto-trigger for Writer (ADR-0006
      decision #2) — explicitly deferred until the gate above exists and is
      confirmed working; borderline-score handling is an open question, not
      decided by omission, per ADR-0006
- [ ] `biohunter report` — static HTML activity report, no server (ADR-0006
      decision #3, MVP scope) — not yet built; Resume Diff and Score above
      now provide the data this needs, so this is a rendering task
- [ ] Job-fit Scorer — ranks postings by scientific fit, location,
      seniority, visa compatibility, salary, user preferences, run
      *before* Writer to decide which postings are worth drafting for at
      all (distinct from Critic's post-draft resume critique above) — not
      yet built (2026-08-07 Critic/Revision handoff)
- [ ] Lightweight weekly cloud token/cost log (ADR-0002) — not yet built;
      lower urgency while running local-only given no ongoing Anthropic API
      access right now

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
- Consider Telegram bot as the approval channel for Filler/Networker gates instead of a full dashboard — revisit once those phases are actually being built (see ADR-0002).
