# BioHunter — Extension Extraction Fixed & Live-Confirmed; Delete Route Built; Scout & Ingestion Subsystem Closed Out

**Session date:** 2026-08-17, continues directly from
`2026-08-17_BioHunter-ExtensionCaptureLive-LLMExtractionScoped-Handoff.md`
(same-day, second doc). That handoff left `linkedin_extract.js`'s
selectors unverified and LLM-assisted extraction scoped-but-undecided —
both are resolved now, see below.

**Why this doc exists:** this session finished the browser-extension
capture work end to end (the last piece of the "three entry points"
design from `2026-08-14_2_BioHunter-SubsystemPlanning-ScoutHandoff.md`),
and the user has explicitly closed out the whole Scout & ingestion
subsystem as a result. **Next session pivots to Captain** — per the
user's own instruction this session, not something inferred. Captain
itself has NOT been designed in any depth yet; see Section 4.

---

## 1. Built and confirmed live this session

- **`linkedin_extract.js` rewritten to avoid LinkedIn's CSS classes entirely.**
  Live DevTools testing (via disposable console diagnostic scripts, not
  guessing) found LinkedIn's current build generates class names as
  short hashes (e.g. `_745ed96f`, `c8199d27`) reassigned on every
  LinkedIn deploy — the OLD selectors weren't wrong, that whole category
  of approach was doomed to keep breaking. Replaced with:
  - **Title & company**: parsed from `document.title` (`"Job Title |
    Company | LinkedIn"`) — stable SEO metadata, not a styled element.
  - **Description**: LinkedIn truncates behind a "...see more" toggle by
    default; the extraction now clicks it, waits ~600ms, then takes the
    largest real text block on the page (excluding a sidebar Premium
    upsell block that would otherwise get picked by mistake).
  - **Location**: no clean metadata source exists for this one, so it
    falls back to pattern matching (`"City, ST"` / `Remote` / `Hybrid` /
    `On-site`), taking the FIRST match in document order — later matches
    turned out to belong to a "similar jobs" module further down the
    page, not the actual posting.
  - **Apply link / Easy Apply detection**: matches on `aria-label`
    (`"Apply on company website"` vs `"Easy Apply to this job"`), NOT
    visible button text — both buttons visually just say "Apply" or
    "Easy Apply", and a text-based search was confirmed live to
    false-positive-match "similar jobs" cards that carry a hidden "Easy
    Apply" badge string in their link text. For the external case, the
    real href is a LinkedIn safety-redirect wrapper
    (`linkedin.com/safety/go/?url=<encoded real URL>&...`) — unwrapped
    to save the actual company application URL instead of LinkedIn's
    tracking link.
  - **User confirmed live** on two real postings: Addition Therapeutics
    (external Apply → correctly extracted the real Greenhouse URL) and
    R&D Partners (Easy Apply → correctly left blank with an explanatory
    placeholder instead of a guess).
- **`capture.js` updated** to show `"This posting uses LinkedIn Easy
  Apply — no external link exists"` as the apply-field placeholder when
  `applyType === "easy_apply"`, so a blank field reads as confirmed-empty
  rather than looking like extraction failed.
- **`capture.js` auto-close on capture** — window now shows a brief
  `"Captured! Closing…"` / `"Already captured — closing…"` message and
  closes itself ~900ms later on success or duplicate, instead of staying
  open with a dashboard link the user said they don't need at capture
  time. Errors still leave the window open. **Not yet live-tested** —
  built this session in direct response to the user's request, not
  clicked through.
- **`delete_posting.py`** (new standalone script, root of the project) —
  deletes a posting by its stored URL, including dependent
  `drafts`/`applications`/`outreach_emails` rows and clearing any other
  posting's `reposted_from_id` pointing at it (schema.sql has no
  `ON DELETE CASCADE`). **User confirmed live**: ran it successfully to
  remove the stale Addition Therapeutics test posting, unblocking
  re-testing of the capture flow.
- **`dashboard.py`: new `/postings/delete` route + "Delete posting"
  button** on `posting_detail()`, same cascade-delete logic as the
  script above, with a JS `confirm()` prompt before submitting (mirrors
  the terminal script's y/N confirmation). Added because the dashboard
  previously had NO delete capability at all — only `mark_stale_route`
  existed, and capture's dedup check matches `(company_id, url)`
  regardless of status, so a stale posting could never be re-captured
  under the same URL without a delete option. **Not yet live-tested** —
  built this session, needs a first click-through (steps given to user,
  outcome not yet reported back).

## 2. Decided, not to re-litigate

- **LLM-assisted extraction (vision or text-based) — not being built.**
  This was scoped in the previous handoff, motivated by selector
  fragility. That motivation is gone now that extraction avoids
  CSS-class matching entirely. User's own words: "No need for
  LLM-assisted extraction since the browser extension works." Don't
  revisit unless a genuinely new motivation shows up — e.g. wanting
  non-LinkedIn site support, or the earlier-floated
  "capture-all-visible-cards-on-a-search-results-page" batch idea, which
  is a distinct goal from selector reliability and was never scoped in
  detail.
- **`applyType: "none"` (neither Apply nor Easy Apply button found) —
  deliberately left untested.** User hasn't encountered a real posting
  shaped like this. The code path exists (falls back to a generic
  placeholder) but isn't verified against a real example. Don't spend
  effort here until one actually shows up.
- **Scout & ingestion subsystem — user considers this complete.**
  Per `2026-08-14_2`'s three entry points (ATS-adapter pipeline, guided
  company onboarding, browser extension capture), the extension was
  explicitly the lowest-priority of the three — now built, live-tested,
  and closed out anyway. `discover_ats.py` / `CustomAPIAdapter` / the
  onboarding wizard from that same doc were NOT touched this session and
  are not part of this closure — flag if the user's "complete" framing
  is meant to include those too, since this session's work only covered
  the extension piece.

## 3. Caveats still standing on the extension work itself

- Title/company/description/location logic confirmed on exactly ONE
  real posting (Addition Therapeutics). Apply/Easy Apply logic confirmed
  on TWO (Addition Therapeutics = external, R&D Partners = Easy Apply).
  Both test postings appear to be on the same current LinkedIn layout —
  worth letting a few more real captures happen during normal use rather
  than assuming full coverage.
- The "first match wins" location heuristic relies on LinkedIn
  consistently placing the real posting's own location before any
  "similar jobs" module in DOM order — confirmed on one posting only.
- The whole rewrite trades one fragility for a different, smaller one:
  hashed CSS classes are gone, but the code now depends on
  `document.title`'s `"X | Y | LinkedIn"` format, the "...see more" /
  "show more" button wording, and the aria-label strings
  `"Apply on company website"` / `"Easy Apply to this job"` staying as
  they are. More stable than build-hash classes, not immune to LinkedIn
  ever changing wording or metadata format.

## 4. Next session: pivot to Captain — scoping status

**Captain is not designed yet.** Per `2026-08-14_2`, this session's
planning work only went deep on Scout & ingestion; Captain, Workspace,
and Writer/export were explicitly deferred. The only concrete note that
exists on Captain so far, from that same handoff:

> "If the next session finds itself wanting a persisted job queue
> (Captain) to show progress on a long-running `discover_ats.py` scan,
> that's a real dependency worth flagging back to the user rather than
> quietly building a mini version of Captain to unblock itself."

That's a hint at shape (a persisted job queue), not a design. Whatever
depth exists beyond that one line should be in `docs/ROADMAP.md`'s "Four
dashboard subsystems" section, per `2026-08-14_2`'s own instruction not
to duplicate that reasoning elsewhere — **next session's real first
step is reading that section, not writing code.**

Worth knowing before that read: `dashboard.py` already has an in-memory,
non-persisted job pattern (`_set_job`/`_get_job`/`_run_generation`/
`_run_scout_job`/`_run_dead_link_check_job`, backed by `run_log` in
`schema.sql` for completed runs only) — likely exactly what Captain is
meant to formalize into something persisted/queued, but that's an
inference from the code, not a confirmed design decision.

## 5. Standing open items, carried forward unchanged (still unresolved)

Everything in `2026-08-14_1`'s Section 4, restated unchanged in
`2026-08-14_2`'s Section 4: Scribe Therapeutics Greenhouse 404, Lever
dead-link detection, "Example Biotech Inc" stale entry, `is_posted:
false` filtering, `cli.py`'s lack of PDF/stability wiring — plus the MVP
verification punch-list (candidate name in PDF, strict/loose stability,
inline bold rendering, word-diff view, dashboard-link footer, browser
notifications), meant to be clicked through by the user directly. No
evidence any of this has been touched since. None of it blocks Captain
work, but none of it's resolved either — worth a real look eventually.

## 6. Working style — unchanged, plus what this session reinforced

Vibe-coded: files uploaded to chat, edited, downloaded, dropped into the
local repo by hand. Every change handed back as a complete file, never a
diff. Explain rationale before coding. Restart the dashboard process
after any `.py` edit. Keep sessions scoped to one subsystem.

Reinforced this session, worth stating explicitly since it came up
directly: **when the user is not comfortable with a step (e.g. DevTools,
Terminal), give exact literal actions — what to click, what to type,
what to paste — not a description of the goal.** Several diagnostic
scripts this session existed specifically so the user could paste one
thing and report back output, rather than being asked to reason about
DOM structure themselves.

## 7. Files to upload next session

**Must-have, to scope Captain for real:**
- `docs/ROADMAP.md` (has whatever real depth exists on Captain's design
  — not read this session, wasn't uploaded)
- This handoff
- `2026-08-14_2_BioHunter-SubsystemPlanning-ScoutHandoff.md` (defines
  what Captain is relative to the other three subsystems — referenced
  here but should be re-uploaded so next session has it directly)

**Likely relevant once Captain's scope is confirmed:**
- Current `dashboard.py` (this session's delete-route version — has the
  in-memory job pattern Captain probably formalizes)
- `schema.sql` (has `run_log`, likely Captain's starting point or close
  to it)
- `cli.py` (if Captain needs to surface CLI-triggered jobs, not just
  dashboard-triggered ones — unconfirmed)

**Not needed:** anything Workspace/Writer-export specific
(`llm.py`, `writer.py`, `revision.py`, `resume_pdf.py`,
`settings_db.py`) or Scout-specific (`detect_ats.py`, `ats/`,
`scout/scraper.py`, `companies.yaml`) — both subsystems are closed for
now, no reason to load their context into a Captain-focused session.
