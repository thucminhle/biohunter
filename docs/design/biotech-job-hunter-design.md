# BioHunter — A Bay Area Biotech Job Hunter Agent Team
### Design Document v0.1

---

## 1. Goals & Scope

Unlike generic job-board aggregators, biotech hiring is heavily **company-website-first** — a huge share of roles never hit LinkedIn/Indeed until days or weeks later, especially at smaller/private biotechs. So the core value of your version isn't "score more listings," it's:

1. **Direct monitoring of a curated list of Bay Area biotech company career pages** (not just job boards)
2. **Human-approved autofill** of application forms
3. **Weekly market intelligence report** — new postings, hiring trends, relevant conferences
4. **Contact discovery + intro email drafting** for warm outreach (with your approval before sending)
5. Reuse your existing **Hermes Agent + n8n** workflow for scoring and resume/bullet assembly, rather than rebuilding it

This system is single-user, self-hosted, and provider-agnostic (cloud or local LLM per role).

---

## 2. Agent Roster

| Agent | Role | Notes |
|---|---|---|
| **Scout** | Monitors company career pages + job boards; detects new/changed postings | Scraper + diff engine, not just LLM |
| **Scorer** | Ranks postings against your profile | **Delegates to your existing Hermes/n8n scorer** via webhook — not rebuilt |
| **Writer** | Assembles tailored resume from your preformed bullets + drafts cover letter | **Delegates to your n8n resume-builder** for assembly; LLM agent handles cover letter + tailoring rationale |
| **Filler** | Opens application forms, pre-fills fields, stops for your review before submit | Browser automation (Playwright), human-in-the-loop gate |
| **Networker** | Finds likely email contacts at target companies (recruiters, hiring managers, team members), drafts intro/outreach emails | Human approval required before any email is sent |
| **Analyst** | Weekly digest: new postings summary, hiring velocity/trends, relevant biotech conferences in the pipeline window | Runs on a cron/weekly trigger |
| **Captain** | Orchestrates run order, rate limits, budget, retries | Thin coordination layer, SQLite-backed |

Nothing here auto-submits an application or auto-sends an email without your explicit click — that's a hard design rule, not just a preference, since biotech is a small world and a bad autofilled application or unsolicited email is reputationally costly.

---

## 3. Architecture

```
                         ┌────────────┐
                         │  Captain   │  (scheduler, budget, SQLite state)
                         └─────┬──────┘
           ┌────────────┬──────┼───────┬─────────────┐
           ▼            ▼      ▼       ▼             ▼
      ┌────────┐  ┌─────────┐┌──────┐┌────────┐ ┌──────────┐
      │ Scout  │  │ Scorer  ││Writer││ Filler │ │Networker │
      │(crawl) │  │(→n8n hook)│(→n8n +LLM)│(Playwright)│ │(search+LLM)│
      └───┬────┘  └────┬────┘└──┬───┘└───┬────┘ └────┬─────┘
          │            │        │        │           │
          ▼            ▼        ▼        ▼           ▼
      ┌─────────────────────────────────────────────────────┐
      │              SQLite: companies / postings /          │
      │     applications / contacts / emails / conferences   │
      └─────────────────────────────────────────────────────┘
                              │
                              ▼
                   ┌────────────────────┐
                   │  Analyst (weekly)  │ → report (email/Telegram/dashboard)
                   └────────────────────┘
```

**LLM provider layer** (shared by Writer, Networker, Analyst):
- One `LLMClient` interface: `chat(messages, tools?) -> response`
- Backends: `AnthropicClient`, `OpenAIClient`, `OllamaClient` (hits `http://localhost:11434/v1/chat/completions` — OpenAI-compatible schema)
- Per-role config (YAML) picks provider + model, so you can route cheap/high-volume tasks (e.g. summarizing a job description) to a local model on your M4, and reserve cloud models for cover letters / outreach emails where quality matters most.

```yaml
# config/roles.yaml
scout_summarizer:
  provider: ollama
  model: qwen2.5:14b
writer_coverletter:
  provider: anthropic
  model: claude-sonnet-5
networker_email:
  provider: anthropic
  model: claude-sonnet-5
analyst_report:
  provider: ollama
  model: qwen2.5:14b
```

---

## 4. Scout: Company Website Monitoring

This is the piece generic job hunters don't do well, so it's worth building carefully.

**Company registry** (`companies.yaml`): name, careers-page URL, ATS platform if known (Greenhouse, Lever, Ashby, Workday are common in biotech — many expose a JSON API even without a public "API" label, e.g. `boards-api.greenhouse.io/v1/boards/{company}/jobs`).

**Detection strategy, in priority order:**
1. **ATS API** if the company uses Greenhouse/Lever/Ashby — cleanest, most stable, respects rate limits naturally.
2. **Structured scrape** of the careers page HTML if self-hosted, with a per-company CSS selector config.
3. **Diff-based fallback**: hash the page, re-check on a schedule, flag for manual selector setup if the hash changes but a known ATS pattern isn't detected.

**Politeness/legal baseline:** respect `robots.txt`, keep checks to 1x/day or a few hours apart per company (not aggressive polling), identify with a real user-agent. This is monitoring public job postings for personal use, which is standard practice, but keep the crawl rate low and cache aggressively so you're not hammering small company servers.

**Output:** new/changed postings land in the `postings` table, flagged `status: new` for the Scorer.

---

## 5. Scorer & Writer: Reusing Hermes + n8n

Rather than re-implementing scoring or resume assembly:

- **Scorer agent = thin wrapper.** It POSTs the posting (title, description, company, location) to your n8n webhook, gets back a score + rationale, writes it to the `postings` table. No LLM call happens in BioHunter itself for scoring — your Hermes/n8n pipeline stays the single source of truth.
- **Writer agent** does two things:
  1. Calls your n8n resume-assembly webhook with the posting + your bullet library, gets back the tailored resume sections.
  2. Uses an LLM call (cloud, for quality) to draft the cover letter and a short "why this role" tailoring note, using the resume sections + posting as context.
- This keeps your two systems cleanly decoupled — BioHunter orchestrates and monitors, Hermes/n8n keeps doing what it already does well.

---

## 6. Filler: Human-Approved Application Autofill

- Playwright-based browser agent that opens the application form and maps your profile fields (contact info, resume upload, standard EEO questions, work-auth questions) to form fields using field-label matching + LLM fallback for unusual layouts.
- **It fills but does not submit.** The browser window stays open (or a screenshot + diff is shown) for your review; you click submit yourself, or approve via a CLI/dashboard prompt.
- Store a per-company "form fingerprint" once solved so repeat applications to the same ATS (e.g. every Greenhouse-based company) reuse the mapping — this is where the effort pays off, since most biotechs cluster on 3–4 ATS platforms.

---

## 7. Networker: Contacts & Outreach

- **Contact discovery**: search company site "team/about" pages, LinkedIn company employee lists (via manual export or a connector, not scraping LinkedIn directly — that violates their ToS), and press releases for names + likely email patterns (`first.last@company.com` inferred from any known company email, verified where possible).
- **Draft, don't send.** Networker drafts a short, specific intro email per contact (referencing the actual role and something concrete about their work), and queues it for your review/edit/send — this also protects you from the LLM hallucinating a detail about a real person.
- Log sent emails and follow-up timing so the weekly report can remind you who's still owed a follow-up.

---

## 8. Analyst: Weekly Report

Runs every Sunday (or your preferred day), pulls from SQLite, and produces:
- New postings this week, grouped by company, with scores
- Applications submitted / pending your review / stalled
- Outreach sent, replies received, follow-ups due
- **Conferences**: a curated watchlist (e.g. JPMorgan Healthcare Conference, Bio International, SLAS, regional biotech mixers) cross-referenced against the current date so you get "coming up in the next 6 weeks" reminders — this can start as a static calendar you maintain, with LLM-assisted summarization of any new conference announcements you paste in.
- Delivered via email or Telegram digest, formatted for a 2-minute read.

---

## 9. Data Model (SQLite)

```
companies(id, name, careers_url, ats_type, last_checked_at)
postings(id, company_id, title, url, description, first_seen_at, status, score, score_rationale)
applications(id, posting_id, status, filled_at, submitted_at, notes)
contacts(id, company_id, name, title, email, source, confidence)
outreach_emails(id, contact_id, posting_id, draft, sent_at, status)
conferences(id, name, start_date, end_date, location, relevance_note)
```

---

## 10. Build Phases

1. **Phase 1 — Scout + storage.** Get the company registry + ATS/scrape detection reliably pulling new postings into SQLite. This alone is already more useful than a generic aggregator.
2. **Phase 2 — Scorer/Writer hooks.** Wire up the n8n webhooks; confirm round-trip scoring and resume assembly.
3. **Phase 3 — Analyst weekly report.** Cheapest to build, immediate visible payoff, good motivation checkpoint.
4. **Phase 4 — Filler.** Highest engineering effort (Playwright + per-ATS form mapping); start with the 1–2 ATS platforms most of your target companies use.
5. **Phase 5 — Networker.** Contact discovery quality will be the limiting factor; start manual (you supply a contacts CSV) before automating discovery.

---

## 11. Stack Recommendation

- **Language:** Python (best ecosystem for scraping/Playwright/LLM tooling; n8n webhooks are language-agnostic anyway)
- **Orchestration:** simple SQLite + APScheduler/cron, no heavy agent framework needed at this scale
- **Browser automation:** Playwright (Python)
- **LLM routing:** thin custom client as in §3 — avoids framework lock-in, easy to swap Ollama ⇄ cloud per role
- **Local models on your M4 (24GB):** Qwen2.5 14B-Instruct (quantized) or Llama 3.1 8B via Ollama for summarization/classification-heavy roles (Scout summaries, Analyst digest drafting); reserve cloud (Claude) for cover letters and outreach emails where nuance/quality matters most.

---

## 12. Guardrails (worth keeping non-negotiable)

- No auto-submit of applications, no auto-send of emails — always a human click.
- Rate-limit all scraping; respect robots.txt.
- No LinkedIn scraping (ToS) — use manual export/connector for that data source instead.
- Log every AI-drafted email/application for your own audit trail.
