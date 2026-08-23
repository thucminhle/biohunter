# Native Resume/Cover-Letter Pipeline Port — Step 1 In Progress — Handoff

Paste this whole document as the first message in a new chat to continue work with full context.

---

## Project summary

BioHunter is a self-hosted, multi-agent job-hunting system (Scout monitors
Bay Area biotech company career pages directly, Scorer ranks postings,
Writer assembles resume + cover letter, Filler auto-fills application
forms for human approval, Networker finds contacts and drafts outreach,
Analyst sends a weekly report — all human-approval-gated for anything
irreversible, no auto-submit/auto-send).

This is a continuation of the session that ported the resume/cover-letter
pipeline off n8n natively into BioHunter's Writer agent, per
`docs/adr/0006-native-pipeline-auto-writer-static-report.md`. That prior
session built `LLMClient` (Step 0, not originally scoped but discovered
missing) and got it working. **This session's task: continue Step 1** —
porting Qdrant retrieval + the 8 n8n selection branches natively — from
where it left off.

## Current state

**Step 0 (`LLMClient`) — done and verified.**
- `src/biohunter/llm.py` — `LLMResponse`, `LLMBackend` protocol,
  `AnthropicClient`, `OpenAICompatibleClient` (shared by Ollama + MLX),
  `LLMClient` (role resolution from `config/roles.yaml` + optional
  per-run override dict).
- Verified via `python -m biohunter.cli verify-llm` against Ollama
  (`writer_selection` → `gemma4:12b-mlx`) and MLX/oMLX
  (`mlx_smoke_test` → `gemma-4-12b-coder-fable5-composer2.5-4bit` via
  `http://127.0.0.1:8000/v1`, requires `OMLX_API_KEY` env var). Both
  returned clean responses. The `--model role=model` override form is
  also verified (swapped `networker_contact_research` to a locally-present
  model and got a clean response).
- **Anthropic backend is implemented but deliberately unverified.**
  Nothing in Step 1's scope calls it (`writer_coverletter` role exists in
  `roles.yaml` but isn't used by anything ported so far — the n8n
  reference pipeline generated the whole cover letter locally). No
  ongoing free tier exists for the API (confirmed via search — one-time
  ~$5 trial credit on a new Console account, phone verification, no
  credit card for the trial itself). Defer setting this up until a role
  actually needs it.
- **Known unverified detail:** whether the n8n workflow's `think` flag
  round-trips correctly through `OpenAICompatibleClient` — it's blindly
  forwarded as an extra kwarg into the JSON body, but the n8n reference
  used Ollama's *native* `/api/chat` endpoint (`$json.message.content`
  parsing confirms this), not the OpenAI-compatible `/v1/chat/completions`
  route this port uses. Not blocking (nothing has exercised `think` yet),
  but flag it if a `--role writer_selection` thinking-mode test ever
  behaves unexpectedly.
- `config/roles.yaml` — `scorer` and `writer_resume_assembly`'s stale
  `n8n_webhook` entries removed (n8n is retired, nothing pointed at them).
  `writer_selection` added (`ollama` / `gemma4:12b-mlx` — matches the n8n
  reference exactly, for parity-checking). A **temporary**
  `mlx_smoke_test` role is still in the file — safe to delete now that
  MLX is verified, wasn't wired into anything real.
- `src/biohunter/cli.py` — added `verify-llm` subcommand (`--role`,
  `--model` override, `--include-anthropic` flag) and
  `_parse_model_overrides()`. Existing `run-scout`/`list-postings`
  commands untouched.
- **Known gap, not yet fixed:** `LLMClient`'s override syntax
  (`--model role=provider/model`) swaps provider and model but not
  `base_url` — can't override a role to point at a different server via
  the override alone, only via editing `roles.yaml`. Not blocking (no
  current use case needs it), but worth fixing if MLX/Ollama provider-swap
  overrides become a real workflow.

**Step 1 (Qdrant retrieval + 8 selection branches) — in progress.**
- `src/biohunter/qdrant.py` — `scroll()` and `fetch_by_section_type()`,
  generalizing all 8 n8n "fetch X catalog" HTTP nodes into one function.
  **Verified against real data**: `fetch_by_section_type('professional_summary')`
  returned 5 real catalog entries (`Data Focus`, `Academia Focus`,
  `Scientist Focus`, `AI Focus`, `LC-MS Focus`) with correct `label`/`text`
  fields, confirming the payload-shape assumptions carried over from the
  n8n export (and from `seed_qdrant.js`) are correct.
- `src/biohunter/selection.py` — built, **not yet verified end-to-end**.
  Contains:
  - `strip_fences()`, `parse_json_response()` — shared JSON-parsing
    helpers (never raise; degrade to a default on bad model output,
    matching every n8n `parse X selection` node's try/catch behavior).
  - `CatalogEntry`, `load_catalog()` — turns raw Qdrant payloads into
    typed objects.
  - `select_variant()` — the shared shape for the 5 "pick exactly one
    labeled variant" branches: summary, intro, story, impact, gratitude.
    Exact-matches the model's answer against catalog labels, falls back
    to the first catalog entry with a logged warning on no match —
    ported from n8n's identical fallback behavior on those 5 branches
    specifically (see gotcha below — heading/bullets/skills branches
    fall back differently and are NOT covered by this function).
  - `SUMMARY_INSTRUCTION`, `INTRO_INSTRUCTION`, `STORY_INSTRUCTION`,
    `IMPACT_INSTRUCTION`, `GRATITUDE_INSTRUCTION` — the 5 branches'
    instruction sentences, copied verbatim from the n8n export's "format
    X catalog" nodes. Not paraphrased or unified into one generic
    sentence — ADR-0006 explicitly said not to improve prompts in the
    same pass as the port.
- **`select_variant()` is verified end-to-end against real data**, not
  just unit-tested: called with the real `professional_summary` catalog
  (5 entries) and an LC-MS-flavored test job description through
  `writer_selection` (Ollama, `gemma4:12b-mlx`), it correctly selected
  the `LC-MS Focus` variant. Confirms the full chain — Qdrant fetch →
  prompt construction → LLMClient call → JSON parsing → exact-match
  validation — works, not just that each piece works in isolation.

**Not started yet:**
- Applying `select_variant()` to the other 4 variant-select branches
  (intro/story/impact/gratitude) — should be mechanical now that summary
  is confirmed working, since they share the same function and only need
  the right catalog fetch (`section_type` values: `cover_letter_intro`,
  `cover_letter_story`, `cover_letter_impact`, `cover_letter_gratitude`)
  and the matching `*_INSTRUCTION` constant already defined in
  `selection.py`.
- Heading selection branch (2-pass: select headings, then select bullets
  within those headings) — **different fallback behavior**: falls back to
  the *full catalog* on zero valid selections, not to a single first
  entry. Do not reuse `select_variant()` for this.
- Bullet selection (second pass of the above) — per-heading exact-match
  validation against the bullets fetched for the selected headings, no
  whole-branch fallback (matches n8n: invalid bullets are just dropped,
  no substitute injected).
- Skills selection — flat catalog, same "drop invalid, no fallback if
  empty" shape as bullets, not the same shape as headings.
- Always-full sections fetch (career_history/education/patents/honors/
  publications) — simplest branch, no LLM call at all, just fetch +
  reshape.
- Cover-letter stitch pass (`edit cover letter` in the n8n export) — one
  more `LLMClient.complete()` call over the merged intro/story/impact/
  gratitude selections, light-edit only, ported verbatim per the exact
  prompt in the export (see the n8n JSON for the literal text — long,
  not reproduced in this handoff, pull from the export directly).
- `assemble draft resume` equivalent — pure Python assembly, no LLM call.
- ATS scoring + critique (Step 2 per ADR-0006, doubles as ADR-0002's
  Critic step) — not started, do not start until all 8 branches + stitch
  + assemble are confirmed working.
- `awaiting_review` status + human-approval gate (Step 3) — not started.

## Known gotchas (carry over, don't re-litigate)

From the n8n implementation, still apply to the native port:
- Qdrant collection is `resume_content` (768-dim, Cosine) — not
  `resume_components`.
- Exact-string matching between LLM selection output and catalog labels
  needs a logged warning + fallback — but **the exact fallback behavior
  differs by branch** (see Step 1 status above): summary/intro/story/
  impact/gratitude → fallback to first catalog entry. Headings → fallback
  to full catalog. Bullets/skills → no fallback, just drop invalid
  entries. Don't accidentally unify these three behaviors into one
  shared helper — that would silently change behavior on 2 of the 3
  shapes.
- Any regex/JSON parsing of LLM output must match the model's actual
  output format exactly — `parse_json_response()` in `selection.py`
  handles this defensively (extracts the first `{...}` block, strips
  markdown fences), but hasn't been stress-tested against a real model's
  quirks yet since only the Step 0 "reply with pong" smoke test has run
  so far.

New this session (native-port-specific, not from the n8n days):
- **Qdrant must be launched from the directory containing the real
  `storage/` folder.** Native Qdrant (not Docker — confirmed via `ps aux`,
  no Qdrant container exists, only n8n's) defaults to a `./storage` path
  *relative to its working directory*. Launching it from
  `~/biohunter` instead of `~` silently created an empty second
  `storage/` folder there and served zero collections — no error, just
  `{"collections":[]}`, which looks like "empty database" rather than
  "wrong database" unless you check `ps`/`lsof` for the process's actual
  `cwd`. **Confirm before assuming Qdrant issues are data problems:**
  ```
  lsof -p $(pgrep qdrant) | grep cwd
  ```
  should show `/Users/thucle`, not `/Users/thucle/biohunter`. A stray
  `~/biohunter/storage` folder may still exist from this — safe to
  delete once confirmed Qdrant isn't currently pointed at it, and
  `.gitignore` should have a `storage/` line to stop it recurring
  silently.
- **Two terminals are in play** (VS Code integrated terminal with the
  project venv active vs. a separate macOS Terminal window, not venv-
  aware). Python/pip commands (`python3 -c ...`, `python -m biohunter...`)
  must run in the venv terminal or they fail with `ModuleNotFoundError`
  even though the code is correct — this has happened twice already this
  session. `curl`/`ps`/`docker`/`lsof`/`kill` work in either.
- oMLX (the MLX server in use, not the `mlx_lm.server` command originally
  assumed) listens on `127.0.0.1:8000/v1` by default, **not** `8080`, and
  requires a Bearer API key on its OpenAI-compatible endpoint (Ollama
  does not) — `OpenAICompatibleClient` now supports optional `api_key`,
  resolved from `roles.yaml` via `${ENV_VAR}` substitution.

## Working style

- Mentoring mode, not autopilot — walk through step-by-step, explain what's
  being built and why. Low-level/teachable code written out for the user
  to type/apply themselves with guidance; heavier implementation (full
  selection-branch logic, backend classes) is fine to write directly, but
  explain what it does rather than handing it over silently.
- Still building git/terminal fluency — explicit step-by-step commands
  with expected output, one command at a time when troubleshooting. User
  pastes back exact terminal output/screenshots — use it to diagnose
  precisely rather than guessing (this mattered a lot this session: the
  Qdrant working-directory bug was only found by asking for `lsof`/`ps`
  output instead of assuming a data/config problem).
- Prefer file-based deliverables (single named file), full-file sync over
  incremental patches for anything nontrivial. If sending an incremental
  patch anyway, say so explicitly.
- Wants free-tier/local-first where possible; flagged discomfort with
  Anthropic API costs — confirmed no ongoing free tier exists (one-time
  ~$5 trial credit only), so cloud-routed roles should stay deferred
  until there's a concrete need, not set up preemptively.

## Files to attach to your first message in the new session

1. **This document.**
2. **`docs/adr/0006-native-pipeline-auto-writer-static-report.md`** — the
   design decision and suggested build order driving this whole task.
3. **`docs/adr/0002-adopt-patterns-from-jht.md`** — defines the Critic
   step this task builds later (Step 2), for when that starts.
4. **`docs/handoffs/2026-08-04-resume-pipeline-e2e-complete.md`** — full
   n8n architecture reference, root-caused failure mode, per-branch
   gotchas.
5. **The n8n workflow export** (was uploaded to the prior session as
   `Resume_Tailoring_3.json` — misleadingly named, it's the actual n8n
   export with every node's literal prompt text, not resume content).
   Needed for the not-yet-ported branches' exact prompt wording (heading
   selection, bullet selection, skills selection, always-full sections,
   the cover-letter stitch pass).
6. **`seed_qdrant.js`** — confirms `resume_content`'s payload field names.
7. **Current `config/roles.yaml`, `src/biohunter/llm.py`,
   `src/biohunter/cli.py`, `src/biohunter/qdrant.py`,
   `src/biohunter/selection.py`** — everything built so far, so the new
   session extends rather than rebuilds. Attach whatever the user has
   actually saved to disk, not this handoff's inline descriptions —
   descriptions summarize, they're not a substitute for the real files
   (in particular, confirm whether `select_variant()` got verified before
   this handoff was generated, and whether `mlx_smoke_test` was deleted
   from `roles.yaml`).
8. **`docs/FILE_TREE.txt`** — current project structure.

`ROADMAP.md` and the other ADRs are optional background, not required to
continue Step 1 directly.
