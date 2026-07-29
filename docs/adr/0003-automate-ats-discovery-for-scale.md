# ADR-0003: Automate ATS discovery via headless-browser network sniffing; extend the adapter registry as new patterns are found

**Status:** Accepted
**Date:** 2026-07-29

## Context

Phase 1's registry work (10 target companies) surfaced two kinds of failure
that the six existing adapters (Greenhouse, Lever, Ashby, Workday, Jobvite,
Jobsyn) can't handle:

- **Exelixis** and **Scribe Therapeutics** — both render their job listings
  client-side via JavaScript. A plain `requests.get()` sees an empty
  placeholder; the real data comes from a JSON call the browser makes after
  page load, invisible to anything that doesn't execute JS. (Scribe also
  cost a wasted round-trip: a guessed Greenhouse board token looked
  plausible in search results but 404'd against the real API — a symptom
  of the same underlying problem, not a one-off typo.)
- **10x Genomics** — not a rendering problem at all. It runs on Eightfold.ai,
  a 7th ATS platform not in `detect_ats.py`'s signature list and not in
  `ats/REGISTRY`.

The DevTools Network-tab technique (open the page, watch requests, find the
JSON call) solved this for Astellas/Jobsyn in Phase 1, but it's a manual,
one-company-at-a-time step. That's fine at n=10. It does not scale to
"hundreds of companies," which is the explicitly stated direction of travel
for the registry.

## Decision

Build `discover_ats.py`: a headless-browser tool (Playwright) that automates
the DevTools step instead of a human performing it per company.

- Navigate to the careers URL headless, wait for network idle (optionally
  simulate a click/scroll for sites that only fetch data on interaction).
- Capture every XHR/fetch response.
- Score each response with a cheap heuristic (list of ≥2 objects; job-shaped
  keys like `title`/`location`/`department`/`id`/`posted`) and output a
  short ranked list of candidate endpoints with a sample record each,
  instead of a human hunting through dozens of requests.
- A human still reviews the top candidate and decides: does it match an
  existing adapter's shape (register it as e.g. another Jobsyn-pattern
  company, no new code), or is it a genuinely new pattern (seed for a new
  adapter, same workflow already used to add Jobsyn)?

This treats the two failure modes differently on purpose:

1. **JS-rendered page, real API underneath** (Exelixis, likely Scribe) —
   fully automatable by the discovery tool; no new adapter code needed once
   the endpoint is found, same as any other known ATS shape.
2. **New platform pattern** (Eightfold) — once identified via the discovery
   tool, add a detection signature to `detect_ats.py` (e.g. `"Powered by
   eightfold.ai"` in the footer, same style as existing Greenhouse/Lever/
   Workday signatures) so every future Eightfold company auto-classifies,
   and add the corresponding entry to `ats/REGISTRY` — the registry is
   already designed to grow this way.

Playwright is already an open item twice on the roadmap (Phase 1's
"Playwright fallback for JS-rendered career pages" and Phase 4's Filler).
This ADR pulls that dependency forward and gives it its first real use, so
the install/learning cost is paid once and reused, not paid twice later.

## Alternatives considered

- **Keep doing DevTools manually per company** — rejected: works at n=10,
  does not work at "hundreds."
- **Use a third-party multi-ATS scraping service/API** (found one during
  this round's research — Apify's multi-ATS actor covers Greenhouse/Lever/
  Ashby/Workday/SmartRecruiters via their public JSON APIs) — rejected for
  the same reason ADR-0001 rejected reimplementing scoring: it's an
  external dependency and a second source of truth for something this
  project already does itself for six platforms, plus recurring per-call
  cost at scale. Revisit only if maintaining adapters becomes the actual
  bottleneck, not before.
- **LLM-based DOM scraping for all custom/no-API sites immediately** —
  rejected for now: no confirmed company on the list yet has *no* JSON API
  at all (Exelixis and Scribe both look like JS-rendered-but-API-backed,
  not fully custom). Worth building once that case is actually confirmed
  to exist in volume, not speculatively now.
- **Fully autonomous new-adapter generation** (LLM writes and registers a
  new adapter without review when the discovery tool finds an unfamiliar
  shape) — rejected: stays human-approval-gated, consistent with the rest
  of this project's design philosophy (Scorer/Writer/Filler/Networker are
  all human-approval-gated too; there's no reason adapter creation should
  be the one autonomous piece).

## Consequences

- Adds Playwright as a new dependency — heavier than `requests` +
  BeautifulSoup, but already unavoidable per the roadmap; this just moves
  up when it's paid for.
- `discover_ats.py` complements rather than replaces `detect_ats.py`:
  `detect_ats.py` still handles fast matching against *known* signatures;
  `discover_ats.py` handles the unknown case where no signature matches.
- Adapter count grows over time as new platforms are found (Eightfold
  becomes the 7th once built) — expected and already supported by the
  `REGISTRY` design, not a departure from it.
- Fully custom sites with no JSON API at all are explicitly **not** solved
  by this ADR — deferred until the discovery tool itself confirms one
  exists, at which point the LLM-DOM-scraping alternative above gets
  revisited on its own merits.
- Registry growth becomes a two-step process per new company going
  forward: run discovery once (automated), then either slot into an
  existing adapter or extend the registry — rather than one step
  (detect_ats.py) that silently fails into a manual DevTools session.
