# BioHunter — Deviation Control, Report Fixes, Progress + Notifications Shipped; Roadmap Refresh Needed Next

**Session date:** 2026-08-14 (continues directly from
`2026-08-13_2_BioHunter-JobsynFixConfirmed-MVPRefocus-Handoff.md`, which
identified "candidate name/contact info never wired into PDF export" as
the one real MVP gap left. **That gap is closed this session** — see
below.)

**Why this doc is different:** the user wants the *next* session to be
mostly planning, not coding — revise `docs/ROADMAP.md` and map concrete
steps to a finished, usable MVP. This doc's job is to hand over a
complete, honest inventory of what changed, what's confirmed vs. still
unverified, and every open item, so that roadmap work is grounded in
what's actually true rather than assumptions. **Read this whole doc
before touching the roadmap** — several items below belong on it.

---

## 1. What shipped this session

Starting point: the only known MVP gap was the missing PDF header. After
closing it, the user actually generated a resume against a real posting
and reported real friction, which drove four more rounds of work:

1. **Candidate settings** — new `/settings` dashboard page, backed by a
   new singleton `candidate_settings` table (`schema.sql`,
   `settings_db.py`, new file). Wired into both PDF export routes in
   `dashboard.py`.
2. **Deviation/stability control** — user reported drafts "significantly
   varying from originals" round to round. Root cause traced (by reading
   `selection.py` in full, not guessed): (a) every revision round was
   explicitly prompted to freely re-select different catalog entries,
   and (b) `stitch_cover_letter()` is the one branch that's a genuinely
   free-form LLM rewrite, not exact-match validated against a catalog.
   Added a per-generate `stability` setting (`strict` / `balanced` /
   `loose`) threaded through every `select_*` branch in `selection.py`,
   `writer.py`'s `generate_draft()`, and `revision.py`'s
   `run_revision_loop()`. Also: `WriterDraft` now carries the 4 raw
   cover-letter building blocks (`cover_letter_blocks`), so a revision
   round can detect "nothing upstream changed" and skip re-running the
   stitch rewrite entirely — this alone should remove a lot of the
   cover-letter drift regardless of stability setting.
3. **Report/PDF rendering fixes** (`report.py`) — no link back to the
   dashboard (added, only when `dashboard_url` is passed); literal
   `**`/`###` characters showing in the PDF (added inline markdown
   rendering, escape-then-convert, XSS-safe); Revision History diffs
   rendering as unreadable horizontal strings (switched prose sections —
   summary, cover letter — to word-level diffing with inline
   `<ins>`/`<del>` spans; bullets stayed line-diffed since they're
   already one-per-line).
4. **Real progress bar + cross-page notification** — `writer.py`/
   `revision.py` gained an `on_step` callback fired at each of 10
   deterministic units of work per round (8 selection branches +
   stitch-or-skip + Critic), so `dashboard.py` computes real
   `step`/`total_steps` and drives an actual `<progress>` bar, not a
   fake animation. Clicking Generate now redirects back to the posting
   page (not a separate status page); that page shows a live progress
   panel instead of the button while a job's in flight. A new
   `/jobs/active.json` endpoint plus an ambient poller in the shared
   page shell (`_page()`) shows a topbar indicator and fires a browser
   `Notification` on completion, from any dashboard page, as long as
   some BioHunter tab is open.

Files touched: `schema.sql`, `settings_db.py` (new), `selection.py`,
`writer.py`, `revision.py`, `diff.py`, `report.py`, `dashboard.py`.
`cli.py`, `db.py`, `config.py`, `resume_pdf.py`, `critic.py` were read
but **not** modified.

---

## 2. Confirmed working vs. NOT yet verified

Per this project's own stated norms (verify real output, don't trust a
description of a change) — being explicit about which is which:

**Confirmed live by the user, this session:**
- Progress bar renders and updates during a real run (1 posting, 1
  revision round, no thinking, `balanced` stability — the no-op default).
- `/settings` page is reachable in the running dashboard.

**NOT yet confirmed — written and syntax-checked (including rendering
the two new `<script>` blocks through real Flask and validating the
resulting JS with `node -c`), but never exercised against a real
running dashboard:**
- Candidate name/contact line actually appearing in a downloaded PDF.
- `strict`/`loose` stability actually producing a visibly different (or
  more stable) result — only `balanced` has been run live so far.
- Inline `**bold**` rendering correctly in the report/PDF.
- The new word-diff rendering in Revision History — **the screenshot
  the original bug report referenced was never actually received in
  chat**; this fix is based on code-reading + the text description only,
  not a visual before/after. Worth a real look once live.
- The dashboard-link footer/header addition.
- Browser notification actually firing, and the topbar indicator, on
  the user's real browser/OS — `Notification` permission behavior
  varies by browser.
- Whether two Generate runs can actually run well concurrently on the
  user's M4 — genuinely unanswered. `llm.py` (which would show whether
  Ollama calls are serialized under the hood) has never been uploaded
  in this entire multi-session thread.

---

## 3. New bug reported this session, NOT yet fixed

User: after returning to the main postings-index page mid-generation and
clicking "Generate" again on the *same* posting from there, it goes
straight back to the progress-bar view instead of, say, warning a
generation is already running.

**Likely explanation, not yet confirmed:** `posting_detail()`'s own
Generate form is correctly replaced by the live progress panel while a
job's in flight (this session's fix, and it works — see above). But the
postings-**index** page's per-card action was never touched this
session, and its card-rendering code was never even viewed. If it POSTs
straight to `/generate` with no in-flight check (plausible, since only
`posting_detail()` got the `_active_generate_job_for_posting()` check),
clicking it would spawn a second, redundant job for the same posting and
land back on `posting_detail`'s progress view — exactly matching what
was reported. **Needs `dashboard.py`'s `index()` route's actual card
markup** (never uploaded/viewed) to confirm and, if so, apply the same
in-flight check there.

---

## 4. Standing open items, carried forward unchanged from the prior handoff

- Scribe Therapeutics — Greenhouse 404, client-rendered careers page, no
  new evidence.
- Lever (Mammoth Biosciences) dead-link detection — still unverified.
- "Example Biotech Inc" — stale leftover, doesn't appear in real
  `companies.yaml`, probably just drop it as a tracked item.
- `is_posted: false` filtering question (Jobsyn) — still not
  investigated.
- `cli.py` has no PDF export path at all, and does not get the new
  `stability` param or candidate-settings wiring — dashboard-only by
  explicit decision this session. Revisit only if CLI usage actually
  matters going forward.

---

## 5. New roadmap-relevant questions for the next session's planning work

These are decisions, not code — good candidates for the roadmap
refresh:
- Is 3-tier deviation control (`strict`/`balanced`/`loose`) enough, or
  is a finer dial worth building?
- Is "notifications only work while a tab is open" an acceptable
  permanent limitation, or does real server-push (SSE/websockets)
  eventually earn its complexity?
- Should concurrent generation be actively serialized/queued in the UI,
  or is it fine as-is once `llm.py` clarifies what actually happens
  under the hood?
- The index-page Generate-button bug above needs a decision + a slot.
- Every item in Section 4 needs either a real roadmap slot or an
  explicit "not doing this" decision — several have been "standing open
  items" across many handoffs now without ever getting one.

---

## 6. Working style — unchanged, still a hard default

Vibe-coded: upload files to chat, AI edits them, user downloads and
drops complete files into the local repo via VS Code/Git. **Every code
change handed back as a complete downloadable file — never a diff,
never a snippet.** Explain rationale before coding. Check for existing
logic before building new. Verify actual output rather than trusting a
description of a change. Restart the dashboard process after any `.py`
edit. Spot-check real results by hand before trusting a bulk operation.
A suspiciously clean number is worth investigating, not just a target
hit. If a fix is described as applied but the same symptom recurs
verbatim, check whether the file on disk actually changed before
assuming the fix was wrong.

---

## 7. Recommended files to upload next session

**Must-have for the roadmap work itself:**
- `docs/ROADMAP.md` — never uploaded or read in this entire
  conversation, and it's the literal file being asked to update.
- `docs/design/biotech-job-hunter-design.md` — already read this
  session, still current, useful for the next AI too.
- This handoff doc.
- `docs/FILE_TREE.txt` — may want a refresh; `settings_db.py` is new
  since it was last generated.

**If continuing the index-page Generate-button bug:**
- `dashboard.py` — the version just produced this session (already
  current).
- Specifically make sure the `index()` route's card-rendering code is
  visible — it was never viewed this session despite the rest of
  `dashboard.py` being fully read.

**If investigating concurrent-generation safety:**
- `llm.py` — never uploaded across this entire multi-session thread,
  despite being imported by nearly everything.
