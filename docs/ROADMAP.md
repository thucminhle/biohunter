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

## Phase 2 — Scorer/Writer hooks
**n8n + Hermes pipeline confirmed production-ready end-to-end as of 2026-08-04
— see ADR-0004 and `docs/handoffs/2026-08-04-resume-pipeline-e2e-complete.md`.
Phase 2 is now unblocked; three integration decisions from ADR-0004 should be
resolved before webhook code is written, not mid-integration:**
- [ ] Decide trigger shape — add/confirm an n8n Webhook trigger node (pipeline
      currently uses `On form submission`) (ADR-0004 #1)
- [ ] Decide webhook request/response contract — what BioHunter posts in vs.
      what the pipeline returns (section text vs. file paths vs. assembled
      cover letter pre/post stitch pass) (ADR-0004 #2)
- [ ] Design Captain's handling of the pipeline's per-execution (not
      per-item) human-approval Wait step before allowing concurrent Writer
      calls (ADR-0004 #3)
- [ ] n8n webhook client for scoring
- [ ] n8n webhook client for resume assembly
- [ ] LLM call for cover letter + tailoring rationale (cloud model) —
      **note: the n8n pipeline now generates the cover letter itself**
      (8-branch intro/story/impact/gratitude selection + LLM stitch pass);
      confirm whether this BioHunter-side item is still needed or is now
      redundant with what the webhook returns
- [ ] Error handling: retry + stall-flagging if n8n unreachable — design
      around the specific failure mode in ADR-0004 (host-resource-contention-
      driven n8n unresponsiveness), not just generic downtime (ADR-0001)
- [ ] Critic step: blind-review pass on Writer's output using a local model
      (no shared context with Writer's prompt) — see ADR-0002
- [ ] Lightweight weekly cloud token/cost log — see ADR-0002

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
