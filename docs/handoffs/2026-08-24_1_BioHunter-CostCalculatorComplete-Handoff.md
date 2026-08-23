# BioHunter — Token Cost Calculator Complete; Scout+Check Combined Job Confirmed

**Session date:** 2026-08-24. Builds directly on
`2026-08-23_3_BioHunter-TokenDashboard-ModelAttribution-Handoff.md`
(same feature area, previous day). Two things close out this session:

1. The token-usage dashboard's cost calculator (flagged as a "known
   gap" in every prior handoff on this feature) is now built, iterated
   on per user feedback, and considered DONE.
2. The user reports Captain roadmap item #4 ("combine Run Scout and
   dead-link-check into one job") is also done and confirmed working
   — **this was NOT built or verified in this thread**; it's carried
   into this handoff as a user-reported status update only. See
   Section 3 for exactly what that means for the next session.

---

## 1. Cost calculator — built and iterated this session, considered done

Built in response to the earlier-flagged gap ("no per-model $/token
table exists"), then revised twice more based on direct user feedback
after seeing it live against a reference tool (tokencalculator.ai).
Final state:

- **New file: `config/model_pricing.yaml`** — manually-maintained
  (NOT live-fetched; no reliable cross-provider pricing API exists,
  and the dashboard's network egress allowlist doesn't include any
  provider's pricing pages anyway). Covers Claude Opus 4.8/Sonnet
  5/Haiku 4.5, GPT-5/GPT-5 mini, Gemini 2.5 Pro/Flash, DeepSeek Chat
  (V3.2), and a free "Local (Ollama/MLX)" row. Each entry has
  `provider`, `input_per_million`, `output_per_million`, and a
  `source` comment. **Needs periodic manual re-verification** — prices
  drift (Anthropic cut Opus pricing ~67% in Feb 2026 as one example)
  and the Haiku 4.5 number specifically is an extrapolation, flagged
  as the least-confident entry in the file's own comments.
- **`dashboard.py` — `/tokens` route, three build passes:**
  1. First pass: two raw number inputs (prompt tokens, completion
     tokens), a live-recalculating table sorted cheapest-first.
  2. Second pass (user feedback: "models aren't grouped by provider,
     I want input-tokens + slider like tokencalculator.ai"): added
     `provider` field to the pricing file; calculator now defaults to
     grouping by provider (alphabetical within group) with a
     "Cheapest first" toggle for the old view. Replaced the two raw
     inputs with one **Input tokens** field + an **Expected output
     size** slider (0-300%) and five presets (Classification 5% / RAG
     Q&A 25% / Chat 50% / Full response 100% / Long generation 200%)
     — same interaction as the reference site. The percentages are an
     approximation of that site's categories, not a fixed standard;
     the slider is the actual source of truth.
  3. Third pass (user feedback: connect the calculator to the actual
     run history): every Tokens value in the per-run table is now a
     clickable link (`bhCalcFromRun()`) that loads that specific run's
     real prompt/completion split into the calculator and scrolls to
     it. Clicking a model row in the calculator (`bhCalcAddColumn()`)
     adds a live, per-row cost column to the per-run table -- computed
     against each row's OWN actual tokens, not the calculator's
     hypothetical input -- toggling off if the same model is clicked
     again, swapping if a different one is clicked.
- Entirely client-side (pricing table embedded as JSON, no Flask route
  or DB round-trip for any of this) -- same reasoning as before:
  the pricing table is small, and instant recalculation matters more
  than server-side computation here.
- **No schema/migration changes this session** -- purely
  `dashboard.py` + the new `model_pricing.yaml` file.

**Confirmed live:** user saw grouped-by-provider display, the
slider/preset UI, and per-provider cost estimates render correctly
against real lifetime token totals (see the three screenshots this
session, matching a real generate+score_batch history). **NOT
explicitly re-confirmed after the third pass** (click-to-populate from
a run row, click-to-add-column) — those were the last edit made; worth
a quick click-through next session before assuming they're flawless,
though they compile clean and follow the same DOM patterns already
proven elsewhere on this page.

## 2. Known gaps, stated deliberately (mostly carried forward, one new)

- **`cost_usd` in `run_log` still NULL everywhere.** The calculator is
  a separate, parallel reference table — it was never wired to write
  back into `run_log.cost_usd`. If you want past runs to show their
  actual historical cost (not just a live what-if), that's a distinct
  follow-on: multiply each row's `prompt_tokens`/`completion_tokens` by
  its own `model` column's rate (a lookup against
  `model_pricing.yaml`, keyed by matching `run_log.model` strings to
  this file's informal display names — **those two naming schemes
  don't currently match** — `run_log.model` holds
  `llm.py`-style strings like `"ollama/gemma4:12b-mlx"` while
  `model_pricing.yaml` uses display names like `"Claude Sonnet 5"` —
  this is a real gap to close before that follow-on is buildable, not
  just a formatting nit).
- **Pricing needs periodic manual re-verification** — no automated
  reminder exists; this is a "remember to check every few months"
  process gap, not a code gap.
- **Long-context / cache / batch pricing tiers not modeled** — every
  rate in `model_pricing.yaml` is the single "standard" rate; several
  providers double pricing above certain context thresholds or offer
  cache-hit/batch discounts (noted per-model in that file's `source`
  comments where known), none of which the calculator accounts for.

## 3. Scout+check combined job — user-reported done, NOT verified in this thread

Per `2026-08-23_2_...`'s Captain-items summary, item #4 was "combine
Run Scout and check for dead links into one job" — listed as ❌ NOT
touched as of that handoff. The user states in this session that this
is now done and confirmed working ("the running scout + check links
also is done and confirmed").

**This thread has no visibility into that work** — no `dashboard.py`
diff for it was shown here, no `detector.py`/scraper code was
reviewed, and no screenshot of it running was provided this session
(contrast with the cost calculator, where three screenshots back the
"confirmed" claim). This was very likely built in a separate AI
session or by the user directly, similar to how the per-run token
view in the prior handoff came from a different session's work.

**Next session should, before relying on this:**
1. Ask the user which file(s) changed for this and get a fresh upload
   of current `dashboard.py` (if not already the same file as this
   session's, which it should be, since this session only touched the
   `/tokens` parts) — confirm no double-implementation or conflicting
   in-flight work the way the token dashboard needed reconciling once
   already this week.
2. Re-read `docs/ROADMAP.md`'s Captain section fresh (every prior
   handoff has flagged this as needed, still not done as of this
   writing) and update its checkboxes for items #3, #4, #6 based on
   actual current file contents, not carried-forward assumptions.
3. If item #4's implementation isn't already documented anywhere,
   this session's user statement should get written up properly once
   the actual mechanism is understood (single job kind? still two
   jobs sequenced under one job_id? UI change only?) rather than
   taken solely on faith.

## 4. Standing open items, carried forward unchanged

Per `2026-08-23_3_...`'s own Section 5 (itself carried forward across
several same-week handoffs) — none of this was touched this session:

- Captain roadmap items #3 (unified progress-bar contract) and #6
  (index-page Generate-button in-flight-check bug) — still open per
  all available evidence; #4 is addressed per Section 3 above, pending
  verification.
- Single-posting generate's cancel mechanism — still only "appears to
  work per user report," not fully traced through `writer.py`.
- Scribe Therapeutics Greenhouse-board 404 / Lever (Mammoth) dead-link
  detection — both still open.
- "Example Biotech Inc" stale test entry still in the DB.
- `is_posted: false` filtering — still open.
- `cli.py`'s lack of PDF/stability wiring — still open.
- MVP verification punch-list (candidate name in PDF, strict/loose
  stability, inline bold rendering, word-diff view, dashboard-link
  footer, browser notifications) — still no evidence of user
  click-through.

## 5. Working style — unchanged

Vibe-coded: files uploaded to chat, edited, downloaded, dropped into
the local repo by hand. Every code change handed back as a complete
file, never a diff or snippet. When two AI sessions (or an AI and
manual/other-AI edits) touch the same file in parallel, always
re-upload the CURRENT file before the next edit request — this
session's Scout+check item is exactly the kind of parallel work that
needs reconciling if it touches the same file this thread already
edited.

## 6. How to pick this up

1. Confirm current `dashboard.py` and `config/model_pricing.yaml`
   match this session's output (`grep -n bhCalcAddColumn
   src/biohunter/dashboard.py` should find it; `grep -n "provider:"
   config/model_pricing.yaml` should show one per model).
2. Click-through test: click a run's Tokens value, confirm the
   calculator populates; click a model row, confirm a cost column
   appears on the run table; click it again, confirm it disappears.
3. Get a fresh upload of whatever changed for Scout+check, per
   Section 3, before treating it as verified.
4. If picking up `cost_usd` backfill: start by deciding how
   `run_log.model` strings map to `model_pricing.yaml` keys (Section 2)
   — that mapping problem comes before any INSERT/UPDATE logic.
5. Otherwise, resume wherever Section 4's carried-forward items point.

---
*(End of handoff — paste everything above this line into a new chat.)*
