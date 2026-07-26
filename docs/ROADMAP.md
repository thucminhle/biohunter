# Roadmap

Mirror these phases as GitHub Issues with checkboxes so progress is visible outside this file too.

## Phase 1 — Scout + storage
- [ ] Turso (libSQL) schema: companies, postings, applications, contacts, outreach_emails, conferences
- [ ] Company registry (`config/companies.yaml`): name, careers URL, known ATS type
- [ ] ATS API adapters (Greenhouse, Lever, Ashby — check which your target companies use first)
- [ ] Fallback scraper + diff detection for self-hosted career pages
- [ ] Rate-limiting / robots.txt respect built in from day one

## Phase 2 — Scorer/Writer hooks
- [ ] n8n webhook client for scoring
- [ ] n8n webhook client for resume assembly
- [ ] LLM call for cover letter + tailoring rationale (cloud model)
- [ ] Error handling: retry + stall-flagging if n8n unreachable (see ADR-0001)

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
