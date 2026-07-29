# Changelog

All notable changes to BioHunter are logged here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Phase 1 registry expansion: Denali (multi-site Workday), Astellas
  (new Jobsyn/NLX adapter — federal-contractor pattern), BioMarin (new
  Jobvite adapter). 505 postings tracked across 5 companies, 0 errors.
  8 passing tests. Full detail: `docs/handoffs/2026-07-29-phase1-registry-complete.md`.
- Stale-posting detection: postings unseen for 30 days after a
  successful company fetch are marked `stale` and excluded from
  `list-postings` by default; applied/rejected postings protected.
- `docs/FILE_TREE.txt` habit added to the handoff process, so new AI
  sessions can see what exists before writing anything.
- Mentoring-style working preference recorded in `docs/HANDOFF.md`:
  step-by-step guided development for teachable code, direct
  implementation (with explanation) for heavier pieces.

### Added (earlier)
- Phase 1 (Scout + storage) initial build: schema, DB layer (local
  SQLite, Turso-ready), ATS adapters for Greenhouse/Lever/Ashby/Workday,
  fallback scraper with diff detection, rate-limiting/robots.txt respect,
  `detect_ats.py` auto-detection helper, CLI (`run-scout`, `list-postings`).
  Genentech and Gilead confirmed live via Workday adapter.
- Session handoff doc structure: `docs/HANDOFF.md` (living, general) +
  `docs/handoffs/` (dated, detailed snapshots per phase transition)

### Added
- Initial repo scaffold: README, ADR structure, roadmap, LLM provider config
- Design document for full multi-agent architecture (Scout, Scorer, Writer, Filler, Networker, Analyst)
- Pre-commit secrets scanning (gitleaks + standard hooks), adopted from Job Hunter Team review — see ADR-0002
- ADR-0002: reviewed JHT, adopted Critic blind-review step + budget logging + secrets scanning, rejected subscription-only model and always-on-scale tooling

<!--
Template for future entries:

## [YYYY-MM-DD] — short description
### Added
- ...
### Changed
- ...
### Fixed
- ...
-->
