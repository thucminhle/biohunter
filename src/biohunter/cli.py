"""
Usage:
    python -m biohunter.cli run-scout
    python -m biohunter.cli list-postings [--exclude KEYWORD,...] [--include KEYWORD,...] [--company NAME]
    python -m biohunter.cli verify-llm [--role ROLE ...] [--model ROLE=VALUE ...] [--include-anthropic]
    python -m biohunter.cli verify-writer --company NAME [--title TITLE]
        (--job-description TEXT | --job-description-file PATH) [--model ROLE=VALUE ...]
    python -m biohunter.cli verify-critic --company NAME [--title TITLE]
        (--job-description TEXT | --job-description-file PATH) [--model ROLE=VALUE ...] [--think]
    python -m biohunter.cli verify-revision --company NAME [--title TITLE]
        (--job-description TEXT | --job-description-file PATH) [--model ROLE=VALUE ...]
        [--revision-rounds N] [--think] [--show-diff]
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging

from pathlib import Path

from .config import load_search_criteria
from .db import get_connection, init_schema
from .critic import critique_draft, parse_score
from .diff import diff_revision_result
from .llm import LLMClient
from .report import render_posting_report, report_id
from .revision import run_revision_loop
from .scout import run_scout
from .writer import generate_draft

# Where `biohunter report` writes its output HTML by default. Not yet
# wired into any DB status (see ROADMAP's `awaiting_review` item) --
# this command is a rendering pass over a fresh pipeline run, same
# persistence-agnostic spirit as verify-revision, just to a file
# instead of stdout. Kept as a plain module constant rather than a
# search_criteria.yaml entry until there's a second thing (an index
# page, say) that also needs to agree on where reports live.
DEFAULT_REPORT_DIR = "reports"

# Fallback defaults if no search_criteria.yaml/example exists at all -- in
# practice load_search_criteria() always finds at least the .example file.
DEFAULT_EXCLUDE_KEYWORDS = ["postdoc", "post-doctoral", "post doctoral", "intern", "internship", "co-op"]

# Same spirit: a blunt, editable default so you're not typing this list every
# time. Includes common per-posting location text on top of city names, since
# ATS location fields vary (some say "South San Francisco, CA", some just
# "Bay Area", some "Remote - US").
DEFAULT_BAY_AREA_LOCATIONS = [
    "bay area", "san francisco", "south san francisco", "oakland", "berkeley",
    "san jose", "redwood city", "foster city", "fremont", "palo alto",
    "menlo park", "emeryville", "mountain view", "santa clara", "hayward",
    "san mateo", "sunnyvale", "vacaville", "richmond, ca", "alameda",
]


def _log_run(conn, status: str, detail: str) -> None:
    conn.execute(
        """INSERT INTO run_log (agent, finished_at, status, detail)
           VALUES ('scout', ?, ?, ?)""",
        (datetime.datetime.now(datetime.timezone.utc).isoformat(), status, detail),
    )
    conn.commit()


def _parse_model_overrides(values: list[str]) -> dict[str, str]:
    """Turns repeated --model role=value flags into the overrides dict
    LLMClient expects. "value" can be a bare model name ("llama3.1:8b")
    or "provider/model" ("ollama/llama3.1:8b") -- LLMClient decides which
    based on whether there's a "/" in it, not this function."""
    overrides: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"--model expects role=value, got: {raw!r}")
        role, value = raw.split("=", 1)
        overrides[role.strip()] = value.strip()
    return overrides


def cmd_run_scout(_args: argparse.Namespace) -> None:
    results = run_scout()

    total_new = sum(r.new_postings for r in results)
    errors = [r for r in results if r.strategy == "error"]

    print(f"Scout run: {len(results)} companies checked, {total_new} new postings.\n")
    for r in results:
        if r.strategy == "error":
            print(f"  [ERROR] {r.company_name}: {r.error}")
        else:
            print(f"  {r.company_name} ({r.strategy}): {r.new_postings} new / {r.total_postings} total")

    conn = get_connection()
    init_schema(conn)
    status = "ok" if not errors else "partial"
    detail = json.dumps(
        {
            "companies_checked": len(results),
            "new_postings": total_new,
            "errors": [{"company": r.company_name, "error": r.error} for r in errors],
        }
    )
    _log_run(conn, status, detail)


def cmd_list_postings(args: argparse.Namespace) -> None:
    criteria = load_search_criteria()

    title_exclude = (
        [k.strip().lower() for k in args.exclude.split(",") if k.strip()]
        if args.exclude is not None else criteria.title_exclude
    )
    title_include = (
        [k.strip().lower() for k in args.include.split(",") if k.strip()]
        if args.include is not None else criteria.title_include
    )
    location_include = (
        [k.strip().lower() for k in args.location.split(",") if k.strip()]
        if args.location is not None else criteria.location_include
    )
    location_exclude = criteria.location_exclude

    conn = get_connection()
    init_schema(conn)

    query = """
        SELECT companies.name, postings.title, postings.location, postings.url
        FROM postings JOIN companies ON postings.company_id = companies.id
        WHERE 1=1
    """
    params: list = []
    if not args.include_stale:
        query += " AND postings.status != 'stale'"
    if args.company:
        query += " AND companies.name = ?"
        params.append(args.company)
    query += " ORDER BY companies.name, postings.title"

    rows = conn.execute(query, tuple(params)).fetchall()

    shown = 0
    for company, title, location, url in rows:
        title_lower = title.lower()
        location_lower = (location or "").lower()

        if any(kw in title_lower for kw in title_exclude):
            continue
        if title_include and not any(kw in title_lower for kw in title_include):
            continue
        if any(kw in location_lower for kw in location_exclude):
            continue
        if location_include and not any(kw in location_lower for kw in location_include):
            continue

        print(f"[{company}] {title} -- {location or 'location n/a'}\n    {url}")
        shown += 1

    print(
        f"\n{shown} / {len(rows)} postings shown "
        f"(title_exclude: {', '.join(title_exclude) or 'none'}; "
        f"location_include: {', '.join(location_include) or 'any'})"
    )


def cmd_verify_llm(args: argparse.Namespace) -> None:
    """Step 0 smoke test: send one trivial message through every role
    (or just the ones named with --role) and print what comes back, so
    a broken base_url/model/API key shows up here instead of mid-port
    inside a selection branch. Anthropic-backed roles are skipped by
    default since they cost real (if tiny) money -- pass
    --include-anthropic once a key is set up and you're ready to spend
    a few cents confirming it."""
    overrides = _parse_model_overrides(args.model or [])
    client = LLMClient(overrides=overrides)

    if args.role:
        roles_to_test = args.role
    else:
        roles_to_test = [
            name for name, cfg in client.roles.items()
            if args.include_anthropic or cfg.get("provider") != "anthropic"
        ]

    for role in roles_to_test:
        cfg = client.roles.get(role, {})
        provider = cfg.get("provider", "?")
        if provider in ("n8n_webhook", "opencode"):
            print(f"[{role}] skipped ({provider} has no LLMClient backend)")
            continue
        try:
            response = client.complete(
                role,
                [{"role": "user", "content": "Reply with exactly one word: pong"}],
            )
            print(f"[{role}] {response.provider}/{response.model} -> {response.text.strip()!r}")
        except Exception as exc:  # noqa: BLE001 - smoke test wants to see every failure, not just crash on the first
            print(f"[{role}] FAILED: {exc}")


def cmd_verify_writer(args: argparse.Namespace) -> None:
    """Runs the full native Writer pipeline (writer.generate_draft) end
    to end against one real posting and prints each section separately,
    so you can read the summary/bullets/cover letter on their own rather
    than as one undifferentiated block -- and so you can compare against
    n8n's output for the same posting for a parity check (ADR-0006 step
    1's stated goal).

    Any selection-branch fallback or dropped-item warning (see
    selection.py's docstrings for which branches fall back how) prints
    to stderr automatically via Python logging's default handler -- no
    extra logging setup needed here, but it means warnings show up
    interleaved with this command's own print() output. That's
    intentional: a fallback firing on a real posting is exactly the
    signal a parity check is trying to catch, not noise to filter out.
    """
    if args.job_description_file:
        with open(args.job_description_file, encoding="utf-8") as f:
            job_description = f.read().strip()
    elif args.job_description:
        job_description = args.job_description.strip()
    else:
        raise SystemExit("verify-writer requires --job-description or --job-description-file")

    overrides = _parse_model_overrides(args.model or [])
    client = LLMClient(overrides=overrides)

    draft = generate_draft(
        client,
        company_name=args.company,
        job_title=args.title or "",
        job_description=job_description,
        think=args.think,
    )

    def _section(title: str, body: str) -> None:
        print(f"\n{'-' * 70}\n{title}\n{'-' * 70}\n{body}\n")

    print(f"\n{'=' * 70}\nWRITER DRAFT -- {draft.company_name} -- {draft.job_title or '(no title given)'}\n{'=' * 70}")
    _section("TAILORED SUMMARY", draft.tailored_summary)
    _section("TAILORED BULLETS (full resume body: career history, experience, skills, education, etc.)", draft.tailored_bullets)
    _section("COVER LETTER", draft.cover_letter)


def cmd_verify_critic(args: argparse.Namespace) -> None:
    """Runs the full native Writer pipeline against one real posting
    (same as verify-writer), then runs Critic's blind-review pass over
    the resulting draft and prints the critique. Two separate --model
    override sets are accepted since Writer and Critic are usually
    different roles/providers (writer_selection is typically local,
    critic_review is typically cloud) -- --model applies to both
    LLMClient calls, so pass writer_selection=... and critic_review=...
    together if you need to override either or both in one run.
    """
    if args.job_description_file:
        with open(args.job_description_file, encoding="utf-8") as f:
            job_description = f.read().strip()
    elif args.job_description:
        job_description = args.job_description.strip()
    else:
        raise SystemExit("verify-critic requires --job-description or --job-description-file")

    overrides = _parse_model_overrides(args.model or [])
    client = LLMClient(overrides=overrides)

    draft = generate_draft(
        client,
        company_name=args.company,
        job_title=args.title or "",
        job_description=job_description,
        think=args.think,
    )

    critique = critique_draft(
        client,
        "critic_review",
        company_name=args.company,
        job_title=args.title or "",
        job_description=job_description,
        tailored_summary=draft.tailored_summary,
        tailored_bullets=draft.tailored_bullets,
        cover_letter=draft.cover_letter,
        think=args.think,
    )

    print(f"\n{'=' * 70}\nCRITIQUE -- {draft.company_name} -- {draft.job_title or '(no title given)'}\n{'=' * 70}\n{critique}\n")
    score_result = parse_score(critique)
    if score_result.score is not None:
        print(f"Score: {score_result.score}/10 -- {score_result.rationale}\n")
    else:
        print("Score: unavailable (critique did not include a parseable SCORE: line)\n")


def cmd_verify_revision(args: argparse.Namespace) -> None:
    """Runs the full revision loop (revision.run_revision_loop) against
    one real posting and prints every round -- draft sections + critique
    -- so you can watch what changes (or doesn't) round to round, same
    "read every round, don't just trust the last one" spirit as
    verify-writer's docstring on fallback warnings.
    """
    if args.job_description_file:
        with open(args.job_description_file, encoding="utf-8") as f:
            job_description = f.read().strip()
    elif args.job_description:
        job_description = args.job_description.strip()
    else:
        raise SystemExit("verify-revision requires --job-description or --job-description-file")

    overrides = _parse_model_overrides(args.model or [])
    client = LLMClient(overrides=overrides)

    result = run_revision_loop(
        client,
        company_name=args.company,
        job_title=args.title or "",
        job_description=job_description,
        revision_rounds=args.revision_rounds,
        think=args.think,
    )

    for rnd in result.rounds:
        label = "FIRST DRAFT" if rnd.round_number == 0 else f"REVISION {rnd.round_number}"
        print(f"\n{'=' * 70}\n{label} -- {args.company} -- {args.title or '(no title given)'}\n{'=' * 70}")
        print(f"\n{'-' * 70}\nTAILORED SUMMARY\n{'-' * 70}\n{rnd.draft.tailored_summary}\n")
        print(f"{'-' * 70}\nTAILORED BULLETS\n{'-' * 70}\n{rnd.draft.tailored_bullets}\n")
        print(f"{'-' * 70}\nCOVER LETTER\n{'-' * 70}\n{rnd.draft.cover_letter}\n")
        print(f"{'-' * 70}\nCRITIQUE\n{'-' * 70}\n{rnd.critique}\n")
        score_result = parse_score(rnd.critique)
        if score_result.score is not None:
            print(f"Score: {score_result.score}/10 -- {score_result.rationale}\n")
        else:
            print("Score: unavailable (critique did not include a parseable SCORE: line)\n")

    if args.show_diff:
        round_diffs = diff_revision_result(result)
        if not round_diffs:
            print(f"\n{'=' * 70}\nDIFFS\n{'=' * 70}\nNo revisions ran (--revision-rounds 0) -- nothing to diff.\n")
        for rd in round_diffs:
            print(f"\n{'=' * 70}\nDIFF -- round {rd.round_from} -> round {rd.round_to}\n{'=' * 70}")
            for sec in rd.sections:
                print(f"\n{'-' * 70}\n{sec.section}\n{'-' * 70}")
                if sec.changed:
                    print(sec.diff_text)
                else:
                    print("(unchanged)")


def cmd_report(args: argparse.Namespace) -> None:
    """Runs the full Writer<->Critic revision loop against one real
    posting (identical to verify-revision) and renders the result as a
    single self-contained HTML file instead of printing to stdout.

    This is the "single-posting report" piece of ADR-0006 decision #3 /
    the ROADMAP's `biohunter report` item -- per the 2026-08-07 handoff's
    explicit scoping, a multi-posting index is a separate, later piece
    and is NOT built here; this command always renders exactly one
    posting per run, same as verify-writer/verify-critic/verify-revision
    already do.

    Persistence-agnostic like every module it calls: nothing here writes
    to the postings DB or touches `status`. It runs the pipeline fresh
    and renders what came back -- if you want this report to reflect a
    posting already sitting in the DB at some status, that wiring is
    still open (see ROADMAP's `awaiting_review` item).
    """
    if args.job_description_file:
        with open(args.job_description_file, encoding="utf-8") as f:
            job_description = f.read().strip()
    elif args.job_description:
        job_description = args.job_description.strip()
    else:
        raise SystemExit("report requires --job-description or --job-description-file")

    overrides = _parse_model_overrides(args.model or [])
    client = LLMClient(overrides=overrides)

    result = run_revision_loop(
        client,
        company_name=args.company,
        job_title=args.title or "",
        job_description=job_description,
        revision_rounds=args.revision_rounds,
        think=args.think,
    )
    round_diffs = diff_revision_result(result)

    # Informational only (see report.py's render_posting_report()
    # docstring) -- mirrors LLMClient.complete()'s own override
    # resolution (roles.yaml.py: "/" in an override swaps provider AND
    # model, otherwise only the model swaps) so this can't drift from
    # what the run actually did.
    model_routing: dict[str, str] = {}
    for role in ("writer_selection", "critic_review"):
        if role not in client.roles:
            continue
        provider = client.roles[role]["provider"]
        model = client.roles[role]["model"]
        if role in overrides:
            override_value = overrides[role]
            if "/" in override_value:
                provider, model = override_value.split("/", 1)
            else:
                model = override_value
        model_routing[role] = f"{provider}/{model}"

    html_out = render_posting_report(
        result,
        company_name=args.company,
        job_title=args.title or "",
        job_description=job_description,
        round_diffs=round_diffs,
        model_routing=model_routing,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rid = report_id(args.company, args.title or "")
    out_path = output_dir / f"{rid}.html"
    out_path.write_text(html_out, encoding="utf-8")

    final_score = parse_score(result.final_critique)
    score_display = f"{final_score.score}/10" if final_score.score is not None else "unavailable"
    print(f"Report written: {out_path}  (final score: {score_display}, {len(result.rounds)} round(s))")


def main() -> None:
    parser = argparse.ArgumentParser(prog="biohunter")
    parser.add_argument(
        "--debug", action="store_true",
        help="Log every LLM call's raw response text (logger.debug across selection.py) "
             "in addition to the normal warnings -- verbose, but shows exactly what a "
             "model returned when a selection falls back or comes back empty, instead "
             "of just that it did.",
    )
    subparsers = parser.add_subparsers(required=True)

    p_scout = subparsers.add_parser("run-scout", help="Run one Scout pass over the company registry")
    p_scout.set_defaults(func=cmd_run_scout)

    p_list = subparsers.add_parser("list-postings", help="List stored postings with keyword/location filtering")
    p_list.add_argument("--exclude", help="Comma-separated title keywords to exclude (default: from search_criteria.yaml)")
    p_list.add_argument("--include", help="Comma-separated title keywords to require, any match (default: from search_criteria.yaml)")
    p_list.add_argument("--location", help="Comma-separated location keywords to require, any match (default: from search_criteria.yaml)")
    p_list.add_argument("--company", help="Filter to a single company name")
    p_list.add_argument("--include-stale", action="store_true", help="Include postings not seen in 30+ days (presumed closed)")
    p_list.set_defaults(func=cmd_list_postings)

    p_verify = subparsers.add_parser("verify-llm", help="Smoke-test every LLMClient role with a trivial round-trip call")
    p_verify.add_argument("--role", action="append", help="Test only this role (repeatable). Default: all roles.")
    p_verify.add_argument(
        "--model", action="append",
        help="Override a role's model for this run, e.g. --model writer_selection=llama3.1:8b "
             "or --model writer_selection=ollama/llama3.1:8b. Repeatable.",
    )
    p_verify.add_argument("--include-anthropic", action="store_true", help="Also test anthropic-backed roles")
    p_verify.set_defaults(func=cmd_verify_llm)

    p_verify_writer = subparsers.add_parser(
        "verify-writer",
        help="Run the native Writer pipeline end-to-end against one real posting and print each section",
    )
    p_verify_writer.add_argument("--company", required=True, help="Company name, e.g. 'Genentech'")
    p_verify_writer.add_argument("--title", help="Job title (optional -- used for cover-letter placeholder substitution)")
    p_verify_writer.add_argument("--job-description", help="Job description text, inline")
    p_verify_writer.add_argument("--job-description-file", help="Path to a file containing the job description")
    p_verify_writer.add_argument(
        "--model", action="append",
        help="Override writer_selection's model for this run, e.g. --model writer_selection=llama3.1:8b. Repeatable.",
    )
    p_verify_writer.add_argument(
        "--think", action="store_true",
        help="Run every branch in 'Thorough (with thinking)' mode, matching n8n's think=true form option. "
             "Default is 'Fast (no thinking)' (think=false) -- per 2026-08-05 parity debugging, this ran "
             "~4-6x faster than omitting the flag (the prior, unintentional default) on the same prompt.",
    )
    p_verify_writer.set_defaults(func=cmd_verify_writer)

    p_verify_critic = subparsers.add_parser(
        "verify-critic",
        help="Run Writer end-to-end against one real posting, then Critic's blind-review pass over the result",
    )
    p_verify_critic.add_argument("--company", required=True, help="Company name, e.g. 'Genentech'")
    p_verify_critic.add_argument("--title", help="Job title (optional)")
    p_verify_critic.add_argument("--job-description", help="Job description text, inline")
    p_verify_critic.add_argument("--job-description-file", help="Path to a file containing the job description")
    p_verify_critic.add_argument(
        "--model", action="append",
        help="Override a role's model for this run (writer_selection=..., critic_review=..., etc). Repeatable.",
    )
    p_verify_critic.add_argument(
        "--think", action="store_true",
        help="Run Writer's branches AND Critic's review in 'Thorough (with thinking)' mode. Default: fast mode.",
    )
    p_verify_critic.set_defaults(func=cmd_verify_critic)

    p_verify_revision = subparsers.add_parser(
        "verify-revision",
        help="Run the full Writer<->Critic revision loop against one real posting and print every round",
    )
    p_verify_revision.add_argument("--company", required=True, help="Company name, e.g. 'Genentech'")
    p_verify_revision.add_argument("--title", help="Job title (optional)")
    p_verify_revision.add_argument("--job-description", help="Job description text, inline")
    p_verify_revision.add_argument("--job-description-file", help="Path to a file containing the job description")
    p_verify_revision.add_argument(
        "--model", action="append",
        help="Override a role's model for this run (writer_selection=..., critic_review=..., etc). Repeatable.",
    )
    p_verify_revision.add_argument(
        "--revision-rounds", type=int, default=1,
        help="Number of revision rounds AFTER the first draft (default: 1). "
             "0 runs Writer once and Critic once, no revision.",
    )
    p_verify_revision.add_argument(
        "--think", action="store_true",
        help="Run every round's Writer branches AND Critic review in 'Thorough (with thinking)' mode. Default: fast mode.",
    )
    p_verify_revision.add_argument(
        "--show-diff", action="store_true",
        help="After printing every round in full, also print a unified diff between each "
             "consecutive pair of rounds (summary/bullets/cover letter diffed separately). "
             "Unchanged sections print '(unchanged)' explicitly rather than being skipped -- "
             "a section that never changes across rounds despite critique feedback is itself "
             "a signal worth seeing, not noise to hide.",
    )
    p_verify_revision.set_defaults(func=cmd_verify_revision)

    p_report = subparsers.add_parser(
        "report",
        help="Run the Writer<->Critic revision loop against one real posting and render "
             "a static HTML report (single posting; see docs/adr/0006 decision #3)",
    )
    p_report.add_argument("--company", required=True, help="Company name, e.g. 'Genentech'")
    p_report.add_argument("--title", help="Job title (optional)")
    p_report.add_argument("--job-description", help="Job description text, inline")
    p_report.add_argument("--job-description-file", help="Path to a file containing the job description")
    p_report.add_argument(
        "--model", action="append",
        help="Override a role's model for this run (writer_selection=..., critic_review=..., etc). Repeatable.",
    )
    p_report.add_argument(
        "--revision-rounds", type=int, default=1,
        help="Number of revision rounds AFTER the first draft (default: 1). "
             "0 runs Writer once and Critic once, no revision.",
    )
    p_report.add_argument(
        "--think", action="store_true",
        help="Run every round's Writer branches AND Critic review in 'Thorough (with thinking)' mode. Default: fast mode.",
    )
    p_report.add_argument(
        "--output-dir", default=DEFAULT_REPORT_DIR,
        help=f"Directory to write the report HTML into (default: {DEFAULT_REPORT_DIR}/). Created if missing.",
    )
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
