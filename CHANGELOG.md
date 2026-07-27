# Changelog

All notable changes to BioHunter are logged here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Phase 1 (Scout + storage): schema, DB layer (local SQLite, Turso-ready),
  ATS adapters for Greenhouse/Lever/Ashby/Workday, fallback scraper with
  diff detection, rate-limiting/robots.txt respect, `detect_ats.py`
  auto-detection helper, CLI (`run-scout`, `list-postings`). 7 passing tests.
  Genentech and Gilead confirmed live via Workday adapter. Full detail:
  `docs/handoffs/2026-07-26-phase1-scout-complete.md`.
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
