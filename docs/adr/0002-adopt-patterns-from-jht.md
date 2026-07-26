# ADR-0002: Adopt three patterns from Job Hunter Team (JHT), reject the rest

**Status:** Accepted
**Date:** 2026-07-26

## Context

Reviewed leopu00/job-hunter-team (the generic, subscription-based, 24/7-scale job hunting agent team this project was originally inspired by) to see what's worth reusing before starting Phase 1 build.

## Decision

Adopt three specific patterns:

1. **Blind-review (Critic) step for the Writer agent.** A second LLM call reviews the Writer's cover letter/tailoring note *without* seeing the Writer's own reasoning or prompt context, catching hallucinated claims before they reach the human. Can run on a local model (QA pass, not creative work) — cheap to add. Target: Phase 2.

2. **Pre-commit secrets scanning.** Adopted `gitleaks` + standard pre-commit hooks (`.pre-commit-config.yaml`, `.gitleaksignore`) now, before any real code or credentials land in the repo. This repo will eventually handle API keys, Turso tokens, and real people's contact emails — worth protecting from day one rather than after an incident.

3. **Lightweight budget logging.** Track cloud LLM token/cost usage per week (simple log, not a full watchdog agent) so cost surprises surface early. Target: build alongside Phase 2 (Writer is the first cloud-cost-heavy role).

## Rejected

- **Subscription-only cost model** (JHT's ADR-0004) — rejected in favor of the existing provider-agnostic, local-first routing (see `config/roles.yaml`). JHT needs a flat subscription because it runs at 24/7, ~400M-token/month scale; this project runs a curated company list at much lower volume, so per-call routing (local for volume, cloud for quality) is the better fit, not a cost compromise.
- **Electron desktop app, Next.js/Supabase web dashboard, multi-CLI agent runtime, daily health-check agents (Dottore/Mantenitore)** — all solve problems of running unattended at scale for many users. This is a single-user tool monitoring a curated list; that scope doesn't exist here, and building for it now would be premature complexity.
- **Telegram bot interface** — noted as a good idea (see ROADMAP, Phase 4) but not adopted as an architectural decision yet; revisit when Filler/Networker approval flows are actually being built and a concrete interface choice is needed.

## Consequences

- Phase 2 gets slightly larger scope (Critic step + budget log) but both are small additions, not new agents.
- Contributors/future-me must run `pre-commit install` once per clone — documented in README.
- Avoided scope creep toward a multi-user, always-on product this project was never meant to be.
