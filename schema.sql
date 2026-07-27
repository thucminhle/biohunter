-- BioHunter Phase 1 schema
-- Target: Turso (libSQL) — SQLite-compatible, so this also runs fine
-- against a plain local .db file during development.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    careers_url     TEXT NOT NULL,
    ats_type        TEXT,               -- 'greenhouse' | 'lever' | 'ashby' | NULL (= fallback scrape)
    ats_slug        TEXT,               -- company identifier the ATS API uses, if different from `name`
    css_selector    TEXT,               -- job-listing selector, only used for fallback scrape
    last_checked_at TEXT,               -- ISO8601
    last_hash       TEXT,               -- content hash from last fallback scrape (NULL if ATS-based)
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS postings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    location        TEXT,
    description     TEXT,
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    status          TEXT NOT NULL DEFAULT 'new',   -- new | scored | applied | rejected | stale
    score            REAL,
    score_rationale  TEXT,
    UNIQUE(company_id, url)
);

CREATE TABLE IF NOT EXISTS applications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id   INTEGER NOT NULL REFERENCES postings(id),
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | filled | submitted | withdrawn
    filled_at    TEXT,
    submitted_at TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name       TEXT NOT NULL,
    title      TEXT,
    email      TEXT,
    source     TEXT,          -- e.g. 'manual_csv', 'company_site', 'press_release'
    confidence REAL
);

CREATE TABLE IF NOT EXISTS outreach_emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id),
    posting_id  INTEGER REFERENCES postings(id),
    draft       TEXT NOT NULL,
    sent_at     TEXT,
    status      TEXT NOT NULL DEFAULT 'draft'  -- draft | approved | sent
);

CREATE TABLE IF NOT EXISTS conferences (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    start_date     TEXT,
    end_date       TEXT,
    location       TEXT,
    relevance_note TEXT
);

-- Phase-2 budget-log table, created now so Scout/Captain can start
-- logging cost-free (scrape/API) runs alongside future LLM-call rows.
CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,       -- 'scout' | 'scorer' | 'writer' | ...
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status      TEXT,                -- 'ok' | 'error' | 'partial'
    detail      TEXT,                -- free-form: counts, error message, etc.
    tokens_used INTEGER,             -- NULL for non-LLM runs like Scout
    cost_usd    REAL
);

CREATE INDEX IF NOT EXISTS idx_postings_status ON postings(status);
CREATE INDEX IF NOT EXISTS idx_postings_company ON postings(company_id);
