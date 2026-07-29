# Roadmap

Mirror these phases as GitHub Issues with checkboxes so progress is visible outside this file too.

## Phase 1 — Scout + storage — code-complete, registry in progress; see docs/handoffs/2026-07-29-*.md
- [x] Turso (libSQL) schema — built, includes `run_log` and posting status lifecycle (new/scored/applied/rejected/stale); still running local SQLite, Turso env vars supported but not yet switched on
- [~] Company registry (`config/companies.yaml`) — 5/10 target companies confirmed live (Genentech, Gilead, Denali, Astellas, BioMarin — 505 postings, 0 errors); 7 remain unresearched (Amgen, 10x Genomics, Exelixis, Guardant Health, Mammoth Biosciences, Nurix Therapeutics, Scribe Therapeutics)
- [x] ATS API adapters — **six now**: Greenhouse, Lever, Ashby, Workday (multi-site support), Jobvite (HTML scrape, pagination gap noted), Jobsyn/NLX (federal-contractor pattern — check Amgen against this before assuming custom scrape needed)
- [x] Fallback scraper + diff detection — built; JS-rendered sites still need DevTools-network-tab technique or eventual Playwright path
- [x] Rate-limiting / robots.txt respect — built
- [x] Stale-posting detection — new: postings unseen for 30 days marked `stale`, excluded from `list-postings` by default; `applied`/`rejected` postings protected
- [ ] Jobvite pagination fix ("Show More" not followed — large categories may undercount)
- [ ] Playwright fallback for JS-rendered career pages — still open
- [ ] `--profile` flag for concurrent multi-search — still open, low priority

## Phase 2 — Scorer/Writer hooks
- [ ] n8n webhook client for scoring
- [ ] n8n webhook client for resume assembly
- [ ] LLM call for cover letter + tailoring rationale (cloud model)
- [ ] Error handling: retry + stall-flagging if n8n unreachable (see ADR-0001)
- [ ] Critic step: blind-review pass on Writer's output using a local model (no shared context with Writer's prompt) — see ADR-0002
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
