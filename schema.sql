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
    cost_usd    REAL,
    -- Added 2026-08-23 (token dashboard v2, per-run view -- previously
    -- this table was only ever aggregated by `agent`, never displayed
    -- per-run). job_id points back at the `jobs` table's own id -- that
    -- table already stores each run's full result data (posting_id,
    -- draft_id, batch results list, etc.) as JSON, so the dashboard
    -- reads links from there at render time instead of duplicating them
    -- here. prompt_tokens/completion_tokens are the split that
    -- tokens_used above has always collapsed into one number -- needed
    -- to compute avg tok/s the same way (completion_tokens / llm_seconds)
    -- the live per-job progress badge already does elsewhere in the app,
    -- so the two numbers agree. llm_seconds is LLM generation time only
    -- (sum of each individual call's elapsed time) -- duration_seconds is
    -- real wall-clock job time (job start to finish) and is usually
    -- larger, since it also includes Qdrant fetches / DB writes that
    -- aren't LLM calls. All five NULL for any run_log row written before
    -- this column set existed, and for non-LLM agents (Scout) going
    -- forward -- see migrate_add_run_log_columns.py for backfilling the
    -- schema on an existing database.
    job_id            TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    llm_seconds       REAL,
    duration_seconds  REAL,
    -- Added 2026-08-23 (3rd addition to run_log this date -- see the
    -- job_id/prompt_tokens/etc. block above for the per-run rework this
    -- builds on). Distinct provider/model string(s) actually used by
    -- this job's LLM calls, e.g. 'anthropic/claude-sonnet-5', sourced
    -- from LLMResponse.provider + '/' + LLMResponse.model (llm.py) --
    -- both always set by every backend, unlike the token/timing fields
    -- above which are best-effort. If a single job's calls used more
    -- than one distinct model (not the case today -- every role in
    -- roles.yaml maps to exactly one model per job kind -- but not
    -- assumed, so this doesn't silently misattribute if that changes),
    -- this holds a comma-separated list of every distinct model used,
    -- not just the first. NULL for any row written before this column
    -- existed and for non-LLM agents (Scout) going forward -- see
    -- migrate_add_run_log_model.py for backfilling the schema on an
    -- existing database (CREATE TABLE IF NOT EXISTS never alters an
    -- already-existing table).
    model             TEXT
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

-- Candidate's own name/contact line for the PDF header (resume_pdf.py).
-- Singleton table (id always 1, enforced by the CHECK) -- there's only
-- one candidate using this tool, so a key-value or per-user table would
-- be unused generality. Editable from the dashboard's /settings page
-- rather than a yaml file, so it's changeable without a redeploy/restart
-- (see the 2026-08-13 handoff discussion on where this should live).
-- Row is upserted, never inserted twice -- save_candidate_settings() in
-- settings_db.py always targets id=1.
CREATE TABLE IF NOT EXISTS candidate_settings (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    candidate_name TEXT,
    contact_line   TEXT,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Added 2026-08-23, dashboard.py Recent Jobs persistence. Previously
-- background job state (generate/batch_generate/score_batch/scout/
-- dead_link_check progress and results) lived ONLY in dashboard.py's
-- in-memory _jobs dict and was explicitly documented as not needing to
-- survive a restart -- that decision is reversed here, per direct
-- request, not a silent addition. `id` reuses the same hex job_id
-- string dashboard.py already generates and puts in every /jobs/<id>
-- URL -- no separate identifier scheme. `data_json` holds the FULL
-- current job dict (every field _set_job() has ever written for that
-- job_id, whatever shape that kind's runner uses) as JSON, same
-- "store the whole thing as one JSON blob, not a normalized column per
-- field" pattern drafts.result_json and run_log.detail already use in
-- this file -- job kinds have different field shapes (see
-- dashboard.py's _job_display()), so a normalized schema here would
-- mean a wide table mostly full of NULLs. `kind`/`status` are pulled
-- out as real columns anyway (not just left inside data_json) so a
-- future query ("how many score_batch runs failed last week") doesn't
-- need to deserialize every row's JSON to filter.
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL,   -- queued | running | done | error | cancelled | interrupted
    data_json  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Added 2026-08-24 (Writer subsystem #4, in-dashboard editor). Holds
-- the CURRENT in-progress hand edit for a posting -- separate from
-- `drafts` (immutable AI-generation snapshots) so diff.py's
-- round-to-round comparison across drafts is never affected by hand
-- edits. One row per posting_id (PRIMARY KEY, not autoincrement),
-- always upserted in place -- this is the current edit, not a
-- history. Seeded from the latest draft's tailored_summary/
-- tailored_bullets/cover_letter the first time a posting is opened
-- for editing. A "reset to AI draft" action DELETEs this row rather
-- than leaving an empty/stale one -- absence of a row means "no
-- active edit," same convention drafts_db.py's get_latest_draft()
-- already uses (None, not an empty record).
-- NOTE FOR db.py's _split_statements(): no semicolons in comments
-- above this line.
CREATE TABLE IF NOT EXISTS final_edit (
    posting_id       INTEGER PRIMARY KEY REFERENCES postings(id),
    tailored_summary TEXT,
    tailored_bullets TEXT,
    cover_letter     TEXT,
    edited_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Added 2026-08-24 (Writer subsystem #4, regenerate-while-editing
-- handling). Preserves an in-progress final_edit row when Regenerate is
-- clicked before it's been saved-as-final or reset -- explicitly
-- archived, not silently discarded and not silently left in final_edit
-- to collide with the fresh draft (this project's own norm of naming
-- real behavior changes rather than letting them happen quietly). Read
-- by the version-history panel (not built yet), flattened
-- chronologically alongside drafts.result_json's own rounds, labeled
-- there as "your edit, before regenerating". One row PER regenerate
-- event -- unlike final_edit (always exactly one current row per
-- posting_id), several archived_edit rows can accumulate for the same
-- posting_id across repeated edit/regenerate cycles, which is
-- intentional: each is a real moment in that posting's history, not a
-- value to overwrite. edited_at is carried over unchanged from the
-- final_edit row it came from (when the edit itself was last saved) --
-- archived_at is when Regenerate triggered this archive, usually a
-- different moment, and both are worth keeping.
-- NOTE FOR db.py's _split_statements(): no semicolons in comments
-- above this line.
CREATE TABLE IF NOT EXISTS archived_edit (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id       INTEGER NOT NULL REFERENCES postings(id),
    tailored_summary TEXT,
    tailored_bullets TEXT,
    cover_letter     TEXT,
    edited_at        TEXT NOT NULL,
    archived_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Added 2026-09-12 (Workspace subsystem, dashboard_settings). Singleton
-- row (id=1, same CHECK/upsert pattern as candidate_settings) holding
-- dashboard-wide presentation preferences -- layout_mode picks which of
-- Workspace's three interchangeable renderers is active -- palette is
-- reserved for the future 10-palette system (roadmap, deferred this
-- session) and only ever holds the one default value for now. Kept as
-- its own table rather than folded into candidate_settings on purpose --
-- one module, one concern, same reasoning settings_db.py's own docstring
-- already gives for why candidate_settings isn't a config yaml file.
-- NOTE FOR db.py's _split_statements(): no semicolons in comments
-- above this line.
CREATE TABLE IF NOT EXISTS dashboard_settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    layout_mode TEXT NOT NULL DEFAULT 'master_detail',
    palette     TEXT NOT NULL DEFAULT 'default',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_postings_status ON postings(status);
CREATE INDEX IF NOT EXISTS idx_postings_company ON postings(company_id);
CREATE INDEX IF NOT EXISTS idx_drafts_posting ON drafts(posting_id);
CREATE INDEX IF NOT EXISTS idx_postings_reposted_from ON postings(reposted_from_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
