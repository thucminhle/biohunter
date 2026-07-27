# Roadmap

Mirror these phases as GitHub Issues with checkboxes so progress is visible outside this file too.

## Phase 1 — Scout + storage — mostly complete, see docs/handoffs/2026-07-26-phase1-scout-complete.md
- [x] Turso (libSQL) schema: companies, postings, applications, contacts, outreach_emails, conferences, run_log — built (`schema.sql`); running local SQLite so far, Turso env vars supported but not yet switched on
- [~] Company registry (`config/companies.yaml`) — 2/10 target companies confirmed working (Genentech, Gilead, both Workday); Denali erroring; 7 more unconfirmed
- [x] ATS API adapters — Greenhouse, Lever, Ashby, **and Workday** (added beyond original scope; Workday confirmed solid on 2 live companies)
- [x] Fallback scraper + diff detection for self-hosted career pages — built, but known gap: can't handle JS-rendered sites (e.g. Astellas)
- [x] Rate-limiting / robots.txt respect — built (`ratelimit.py`)
- [ ] Jobvite adapter — new gap identified (BioMarin uses Jobvite, no adapter yet)
- [ ] Playwright fallback for JS-rendered career pages — new gap identified, may pull forward from Phase 4

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
