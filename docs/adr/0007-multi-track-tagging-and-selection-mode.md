# ADR-0007: Multi-track resume/posting tagging, recruiter-mode role discovery, and configurable selection mode

**Status:** Proposed
**Date:** 2026-09-08
**Builds on:** ADR-0002 (Critic/blind-review design), ADR-0006 (native pipeline; raised but did not decide the "auto-trigger Writer above a score threshold" idea, see Consequences there)

## Context

The candidate maintains three resumes targeting distinct role families
(technician, principal scientist, AI-driven research scientist). Today
BioHunter has no concept of "track": `search_criteria.yaml` is a single
flat file, the Qdrant `resume_content` collection is one shared pool with
no track dimension, and Scout/Scorer operate against "the candidate" as
if there were only one profile.

This creates two concrete problems:

1. **Discovery config is hand-curated.** Target job titles and the ATS
   keyword bank Scout/Scorer rely on are manually written into
   `search_criteria.yaml` rather than derived from what the resumes
   actually contain, and there is no per-track version of this file.
2. **A single Scout feed cannot serve three tracks without redundant
   crawling.** Running three fully separate Scout/Scorer pipelines (one
   per track) would re-crawl the same company career pages three times
   over. A posting can also legitimately belong to more than one track
   (e.g. an "AI-driven Research Scientist" posting may also fit the
   `principal_scientist` catalog if senior enough) -- a single-label
   scheme would force an arbitrary choice.

Separately, ADR-0006 raised, but left "Proposed" rather than decided,
the idea of auto-triggering Writer once a posting's Scorer score clears
a threshold, as an alternative to the candidate manually selecting every
posting from the dashboard queue. That decision is folded into this ADR
since it is the same "what happens to a posting after Scout finds it"
question, one step further downstream than tagging.

## Decision

**1. Recruiter-mode (`src/biohunter/recruiter.py`).** A single-shot LLM
module, following the same "one blind-judgment call" pattern as
`scorer.py` rather than Writer's multi-branch selection machinery. Run
once per track (not per posting, not per job-search session): reads that
track's tagged resume content from Qdrant and outputs (a) ~20 target job
titles ranked by fit and (b) a per-title/per-cluster ATS keyword bank.
Output is written to `config/search_criteria.yaml`, restructured from a
flat file to one top-level section per track. Re-run periodically (on
resume update, or on a schedule), not treated as one-time setup.

**2. Track as a first-class tag on both the resume catalog and
postings.**

- Add a `track` field to every Qdrant `resume_content` payload entry, so
  Writer's selection branches can filter to the correct resume's catalog
  instead of the shared pool.
- Add two new relational tables to `schema.sql`, following the project's
  existing normalized-table convention (companies/postings/drafts) rather
  than a JSON blob or comma-separated string:

```sql
CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE   -- 'technician' | 'principal_scientist' | 'ai_data'
);

CREATE TABLE IF NOT EXISTS posting_tags (
    posting_id INTEGER NOT NULL REFERENCES postings(id),
    tag_id     INTEGER NOT NULL REFERENCES tags(id),
    confidence REAL,            -- routing step's confidence, if the classifier provides one
    PRIMARY KEY (posting_id, tag_id)
);
```

Multi-tag postings are just multiple rows in `posting_tags` -- no schema
change needed to go from one tag to several.

**3. A routing step between Scout and Scorer.** After Scout finds a
posting (from a tracked career page or LinkedIn/Indeed), a lightweight
classification pass -- routed via `scout_summarizer` in `config/roles.yaml`,
the same cheap local-model role already used for high-volume, low-stakes
work -- reads the title/description and inserts one `posting_tags` row per
matching track. This runs against a single Scout feed; company career
pages are not re-crawled per track.

**4. Scorer becomes track-aware.** `score_posting()` reads a posting's
tags, and for each matching track, judges fit against that track's
Qdrant catalog and `search_criteria.yaml` section rather than a single
undifferentiated candidate profile.

**5. Configurable selection mode, resolving ADR-0006's open question.**
Add to `candidate_settings` (chosen over a global constant specifically
because this table already exists to hold dashboard-editable preferences
without a redeploy):

```sql
ALTER TABLE candidate_settings ADD COLUMN selection_mode TEXT NOT NULL DEFAULT 'manual';
   -- 'manual' | 'auto' | 'suggest'
ALTER TABLE candidate_settings ADD COLUMN auto_score_threshold REAL DEFAULT 8.0;
   -- only read when selection_mode is 'auto' or 'suggest'
```

- `manual` -- unchanged current behavior: posting reaches `status =
  'scored'`, sits in the dashboard queue, candidate selects it, Writer
  runs on click.
- `auto` -- once Scorer writes a score, a dispatcher checks it against
  `auto_score_threshold`; if it clears the bar, Writer is enqueued
  automatically with no human selection step. This realizes ADR-0006's
  auto-trigger idea. The no-auto-submit rule (design doc §12) is
  unaffected -- Writer/Critic/revision run untouched, the candidate still
  manually reviews and submits the final documents.
- `suggest` -- same threshold check, but instead of auto-enqueuing,
  flags the posting (e.g. surfaced pre-checked / sorted to top of the
  dashboard) for one-click confirm or dismiss.

Default every track to `manual` until Scorer has run long enough against
real tagged postings to see each track's score distribution -- there is
no principled default for `auto_score_threshold` before that data exists.

## Alternatives considered

- **Comma-separated tag string or JSON array on `postings` instead of a
  join table.** Rejected: makes "all technician postings" a full-table
  scan instead of an indexed join, and the rest of the schema already
  distinguishes real columns from JSON blobs specifically for filterable
  fields (see `run_log`/`drafts` denormalization comments in `schema.sql`).
- **Three fully separate Scout/Scorer pipelines, one per track.**
  Rejected: redundant crawling of the same career pages three times over.
- **Single-label routing (one track per posting).** Rejected: a posting
  can genuinely fit more than one track (e.g. senior AI-research roles
  overlapping with principal-scientist scope), and forcing a single label
  would either drop it from a track's queue where it belongs, or require
  an arbitrary tie-break rule with no clear correctness criterion.
- **`selection_mode`/`auto_score_threshold` as one global setting.**
  Considered simpler to implement, but the three tracks likely have
  different score distributions and different tolerance for false
  positives (e.g. higher-volume/lower-stakes technician roles vs. fewer/
  higher-stakes principal-scientist roles). Left as an open
  implementation question rather than decided here: these fields may need
  to move onto a per-track table (alongside `tags`) instead of the
  singleton `candidate_settings` row. Whoever implements this should
  resolve it explicitly rather than defaulting to global by omission.

## Consequences

**Easier:**
- Target titles and ATS keywords are generated from what the resumes
  actually say, refreshable on demand, instead of hand-maintained.
- One Scout feed serves all three tracks; no redundant crawling.
- Dashboard filtering by track ("show me all `technician` postings")
  becomes a straightforward indexed join.
- The `auto`/`suggest` split gives a real middle ground between full
  manual review and unattended operation, without touching the
  no-auto-submit boundary.

**Harder / new surface area:**
- Qdrant payloads, `search_criteria.yaml`, and Scorer all gain a `track`
  dimension that must stay consistent; a track added to one and not the
  others will silently produce empty results rather than an error.
- The routing step is a new LLM-dependent point of failure between Scout
  and Scorer -- a misrouted or untagged posting won't be scored against
  the track it should be, and won't surface in that track's dashboard
  filter.
- `auto` mode changes the risk profile from "candidate reviews every
  posting before Writer runs" to "candidate reviews every posting after
  Writer runs" -- more generation volume (and LLM cost) if
  `auto_score_threshold` is set too low before there's data to calibrate it.

**Given up / deferred:**
- Per-track `selection_mode` is left as an open decision for the
  implementer, not resolved by this ADR -- see Alternatives considered.
- Threshold calibration is explicitly deferred until real score
  distributions exist per track; this ADR does not pick a production
  default beyond the placeholder `8.0`.
