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
    score            REAL,   -- job-FIT score (candidate/location/seniority), written by
                              -- scorer.py's `biohunter score-postings` -- NOT Critic's
                              -- resume-quality score, which lives on drafts.final_score
                              -- instead (see that table's comment). Column existed since
                              -- Phase 1 -- as of 2026-08-09 something finally populates it.
    score_rationale  TEXT,
    stale_at         TEXT,   -- ISO8601 timestamp of the moment status became 'stale'.
                              -- Set once and never overwritten on re-marks (writers should
                              -- use COALESCE(stale_at, datetime('now')) so re-running a
                              -- stale-check job doesn't reset the clock). NULL for any
                              -- posting that has never been stale. This is what repost
                              -- turnaround time is measured FROM -- added 2026-08-13
                              -- alongside repost tracking below, before which there was no
                              -- record of when a posting went stale, only that it was.
    reposted_from_id INTEGER REFERENCES postings(id),
                              -- Set ONLY on a newly-inserted row that detector.py's repost
                              -- matcher believes is the same role reappearing under a new
                              -- URL. Points back at the OLD stale row. The old row is never
                              -- mutated or revived (deliberate choice -- see
                              -- 2026-08-13 handoff's design discussion: preserves history
                              -- Critic/Writer output may already reference by id). NULL for
                              -- every normal posting, including the old stale one itself.
    repost_match_type TEXT,  -- How reposted_from_id was determined, e.g. 'exact_title'.
                              -- Reserved values as matching strategies are added (fuzzy
                              -- title, description similarity, manual). NULL unless
                              -- reposted_from_id is set.
    repost_similarity REAL,  -- 0.0-1.0 confidence that this is really the same role, not a
                              -- different one that happens to share a title. 1.0 for an
                              -- exact title match. Leaves room for a future fuzzy-match
                              -- score without a schema change. NULL unless
                              -- reposted_from_id is set.
    repost_turnaround_days REAL,
                              -- Denormalized julianday(this.first_seen_at) -
                              -- julianday(old.stale_at), frozen at detection time -- same
                              -- pattern as drafts.final_score being denormalized off
                              -- result_json, so the dashboard can show/sort/filter on this
                              -- without a join+computation on every page load. NULL unless
                              -- reposted_from_id is set.
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

-- Added alongside the dashboard (the "dynamic dashboard" ADR-0006
-- deferred, now built on direct request -- see docs/adr/0006). One row
-- per generation RUN, not per posting: clicking "Regenerate" adds a
-- new row rather than overwriting, so a posting's generation history
-- is never lost even though the dashboard UI only surfaces the latest
-- one today. `result_json` holds the full RevisionResult (final_draft,
-- final_critique, every round) as JSON -- see drafts_db.py for the
-- serialize/deserialize helpers. writer.py/critic.py/revision.py
-- themselves are unchanged. `final_score` is denormalized from
-- result_json (Critic's parsed SCORE line for the final round) purely
-- so the dashboard's posting list can show a score badge without
-- deserializing every draft's full JSON on every page load.
-- NOTE FOR db.py's _split_statements(): no semicolons in comments
-- above this line -- the naive splitter doesn't strip comments first.
CREATE TABLE IF NOT EXISTS drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id      INTEGER NOT NULL REFERENCES postings(id),
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    revision_rounds INTEGER NOT NULL,   -- rounds AFTER the first draft, matching run_revision_loop()'s own param
    final_score     INTEGER,            -- Critic's 1-10 score for the final round, NULL if unparseable
    result_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_postings_status ON postings(status);
CREATE INDEX IF NOT EXISTS idx_postings_company ON postings(company_id);
CREATE INDEX IF NOT EXISTS idx_drafts_posting ON drafts(posting_id);
CREATE INDEX IF NOT EXISTS idx_postings_reposted_from ON postings(reposted_from_id);
