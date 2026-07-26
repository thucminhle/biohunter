# BioHunter

A self-hosted, multi-agent job-hunting system for Bay Area biotech roles: monitors company career pages directly, scores/tailors applications via an existing Hermes Agent + n8n pipeline, fills applications for human approval, finds contacts and drafts outreach, and sends a weekly report.

**Status:** 🚧 Phase 1 (Scout) — see [ROADMAP.md](docs/ROADMAP.md)

## Why this exists

Generic job aggregators miss a lot of biotech hiring, which happens company-website-first. Full design rationale: [`docs/design/biotech-job-hunter-design.md`](docs/design/biotech-job-hunter-design.md).

## Tool stack

| Piece | Tool |
|---|---|
| Editor | VS Code |
| Local LLM inference | Ollama, MLX (Apple Silicon), OpenCode |
| Cloud LLM | Claude (Anthropic API) |
| Workflow / scoring / resume assembly | n8n + Hermes Agent (external, called via webhook) |
| Database | Turso (libSQL — SQLite-compatible, edge-hosted) |
| Containerization | Docker |
| Image gen (optional, e.g. for outreach visuals/decks) | ComfyUI |
| Browser automation | Playwright |

## Repo layout

```
biohunter/
├── README.md              ← you are here
├── CHANGELOG.md            ← dated log of what shipped
├── docs/
│   ├── design/             ← full design docs
│   ├── adr/                ← architecture decision records
│   └── ROADMAP.md          ← build phases, checked off as you go
├── config/
│   └── roles.yaml          ← per-agent LLM provider routing
├── .github/workflows/      ← CI (add once tests exist)
└── src/                    ← (not yet scaffolded — Phase 1 target)
```

## Quick start

One-time setup, before writing any code:
```bash
pip install pre-commit --break-system-packages
pre-commit install
```
This enables secrets scanning (gitleaks) on every commit — see [ADR-0002](docs/adr/0002-adopt-patterns-from-jht.md).

The rest of the quick start will be filled in once Phase 1 (Scout) lands. For now, see the design doc and roadmap.

## Contributing (to yourself, six months from now)

Before changing an architectural decision, check `docs/adr/` — there's probably already a reason it's built that way.
