from __future__ import annotations

import dataclasses
import datetime
from typing import Callable

from bs4 import BeautifulSoup

from ..ats import REGISTRY
from ..ats.base import RawPosting
from ..ats.custom_api import CustomAPIAdapter, load_custom_api_config
from ..config import CompanyConfig, load_companies
from ..db import get_connection, init_schema
from . import scraper
from .ratelimit import RateLimiter

# A posting not seen in a Scout run for this many days is presumed closed/
# filled and marked 'stale'. This only ever runs after a SUCCESSFUL fetch
# for that company in the current pass -- a failed run tells us nothing
# about which postings are still live, so it must never trigger staleness.
STALE_AFTER_DAYS = 30


@dataclasses.dataclass
class ScoutResult:
    company_name: str
    strategy: str          # 'ats' | 'scrape' | 'error'
    new_postings: int
    total_postings: int
    error: str | None = None


def _clean_description(raw: str | None) -> str | None:
    """Strips HTML down to plain text. ATS public APIs conventionally
    return job descriptions as HTML, not plain text -- confirmed for
    Greenhouse (see greenhouse.py's own "HTML; caller may strip tags"
    comment, previously never acted on), and Lever/Ashby's APIs follow
    the same convention, so this is applied centrally here rather than
    per-adapter -- every ATSAdapter's output goes through the same
    cleanup on the way into the DB, including any adapter added later,
    with no per-adapter opt-in to remember.

    Deliberately only breaks lines at BLOCK-level tags (p, div, li,
    headings, table rows) -- a naive `get_text(separator="\\n\\n")`
    inserts that separator between every child node BeautifulSoup
    concatenates, including inline tags like <strong>/<em>/<a>, which
    fragments ordinary sentences ("We are seeking a" / "Senior
    Scientist" / "to join..." as three fake paragraphs) any time a
    posting bolds a word. Caught this by testing against a realistic
    Greenhouse `content` payload, not by inspection -- worth remembering
    if this function ever gets "simplified" back to a bare get_text()
    call. <li> items get a "- " prefix so a bullet list survives as a
    bullet list, not a run-on sentence.

    Safe to call unconditionally, including on text that's already
    plain: the fallback scraper (scraper.py's extract_postings()) never
    sets description at all, so this only ever touches ATS-sourced
    text, and BeautifulSoup is a no-op on a string with no tags in it.

    KNOWN LIMITATION, not solved here: a description containing a
    stray '<' as plain text (e.g. scientific notation like "IC50 <
    10nM") can confuse an HTML parser into treating it as the start of
    a tag. Rare enough in practice not to block on, but worth knowing
    if a posting's stored description ever looks like it's missing a
    clause right after a "<" or "<=" comparison.
    """
    if not raw:
        return raw
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "- ")
    for tag in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
        tag.append("\n\n")
    text = soup.get_text()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def _get_or_create_company_id(conn, company: CompanyConfig) -> int:
    row = conn.execute(
        "SELECT id FROM companies WHERE name = ?", (company.name,)
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        """INSERT INTO companies (name, careers_url, ats_type, ats_slug, css_selector)
           VALUES (?, ?, ?, ?, ?)""",
        (company.name, company.careers_url, company.ats_type, company.ats_slug, company.css_selector),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (company.name,)).fetchone()
    return row[0]


def _upsert_postings(conn, company_id: int, postings: list[RawPosting]) -> int:
    """Insert new postings, refresh last_seen_at on existing ones. Returns count of new postings.

    BEHAVIOR CHANGE from before this fix, stated explicitly rather than
    left implicit: previously, an already-seen posting only ever got
    last_seen_at refreshed -- its description (if any) was whatever it
    was on first sight, forever. Now description is refreshed on every
    sighting too (via COALESCE, so a fetch that returns nothing for
    description -- the fallback scraper always, or a transient ATS
    field miss -- never blanks out text that was already there).
    Companies do edit live postings; the dashboard's "Regenerate" flow
    should draft against current wording, not whatever a posting said
    weeks ago. One consequence worth knowing: if you ever hand-edit
    postings.description directly (e.g. via the dashboard's paste-box,
    for a fallback-scraped posting with no ATS description), a later
    Scout run CAN overwrite that edit if the source now returns real
    content for it -- there's no "manually edited, don't touch" flag on
    the row. Not built here; flagging it as a real, known interaction
    rather than a silent surprise.

    ADDED 2026-08-13: a genuinely new (company_id, url) posting now also
    triggers _link_repost_if_exact_match() right after insert, to catch
    reposts that get a new URL from the ATS (the normal case) rather
    than the old row just being refreshed. See that function's own
    docstring for the exact-title-only, skip-on-ambiguity matching rule.
    """
    new_count = 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for p in postings:
        description = _clean_description(p.description)
        existing = conn.execute(
            "SELECT id FROM postings WHERE company_id = ? AND url = ?", (company_id, p.url)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE postings SET last_seen_at = ?, description = COALESCE(?, description) WHERE id = ?",
                (now, description, existing[0]),
            )
        else:
            conn.execute(
                """INSERT INTO postings (company_id, title, url, location, description, status)
                   VALUES (?, ?, ?, ?, ?, 'new')""",
                (company_id, p.title, p.url, p.location, description),
            )
            new_count += 1
            _link_repost_if_exact_match(conn, company_id, p.title, p.url)
    conn.commit()
    return new_count


def _normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace, for exact-repost title matching.
    Deliberately not more aggressive than this -- no punctuation
    stripping, no stemming -- see _link_repost_if_exact_match()'s
    docstring for why a cheap, conservative match was chosen over fuzzy
    matching for this first pass."""
    return " ".join(title.split()).lower()


def _link_repost_if_exact_match(conn, company_id: int, title: str, url: str) -> None:
    """Called right after inserting a brand-new posting (i.e. one whose
    (company_id, url) didn't already exist). If EXACTLY ONE stale
    posting at this company shares the same normalized title, treat the
    new posting as a repost of it: set reposted_from_id, record how the
    match was made, and compute turnaround time from the old row's
    stale_at to the new row's first_seen_at.

    Deliberately conservative on ambiguity: if a company has more than
    one stale posting with that exact title (e.g. a recurring req like
    "Research Associate" reused across teams), this SKIPS linking
    entirely rather than guessing -- a wrong link would silently
    corrupt repost_turnaround_days, whereas skipping just leaves
    reposted_from_id NULL, indistinguishable from an ordinary new
    posting. This was an explicit call made with the user rather than
    an assumption: 'most recent stale match' and 'oldest stale match'
    were both considered and rejected in favor of skip-on-ambiguity.

    Only exact-title matching is implemented (repost_match_type =
    'exact_title', repost_similarity = 1.0 always, for now) -- fuzzy
    title/description similarity is a documented stretch goal in
    schema.sql's own column comments, not built here.

    The old row's stale_at can be NULL for rows marked stale before
    this feature existed -- the link is still recorded in that case,
    just without a turnaround number, so historical data isn't silently
    dropped.
    """
    stale_rows = conn.execute(
        "SELECT id, title, stale_at FROM postings WHERE company_id = ? AND status = 'stale'",
        (company_id,),
    ).fetchall()
    normalized_target = _normalize_title(title)
    matches = [r for r in stale_rows if _normalize_title(r[1]) == normalized_target]
    if len(matches) != 1:
        return  # zero matches, or ambiguous (2+) -- skip either way, see docstring

    old_id, _old_title, old_stale_at = matches[0]
    new_row = conn.execute(
        "SELECT id FROM postings WHERE company_id = ? AND url = ?", (company_id, url)
    ).fetchone()
    if new_row is None:
        return  # shouldn't happen -- we just inserted it -- but never break Scout over this
    new_id = new_row[0]

    if old_stale_at:
        conn.execute(
            """UPDATE postings
               SET reposted_from_id = ?,
                   repost_match_type = 'exact_title',
                   repost_similarity = 1.0,
                   repost_turnaround_days = julianday(first_seen_at) - julianday(?)
               WHERE id = ?""",
            (old_id, old_stale_at, new_id),
        )
    else:
        conn.execute(
            """UPDATE postings
               SET reposted_from_id = ?,
                   repost_match_type = 'exact_title',
                   repost_similarity = 1.0
               WHERE id = ?""",
            (old_id, new_id),
        )


def _mark_stale_postings(conn, company_id: int, run_time: datetime.datetime) -> int:
    """Mark postings not seen in this company's last STALE_AFTER_DAYS worth
    of successful Scout runs as 'stale'. Never touches postings you've
    already progressed (status 'applied' or 'rejected') -- staleness here
    means "no longer visible on the source", not a judgment on postings
    you've already acted on. Returns count of postings newly marked stale.

    Also stamps stale_at (via COALESCE, so it's set exactly once, same
    convention as dashboard.py's mark_stale_route -- the dashboard's
    manual dead-link-confirm path and this automatic path are the only
    two writers of status='stale', and both need to leave the same kind
    of timestamp behind for repost_turnaround_days to mean anything
    regardless of which path a given posting went stale through).
    Uses SQL datetime('now'), not a Python-formatted timestamp, to match
    first_seen_at's own DEFAULT (datetime('now')) in schema.sql -- both
    need to be directly comparable via julianday() in
    _link_repost_if_exact_match() without a format mismatch.
    """
    cutoff = (run_time - datetime.timedelta(days=STALE_AFTER_DAYS)).isoformat()
    cur = conn.execute(
        """UPDATE postings SET status = 'stale', stale_at = COALESCE(stale_at, datetime('now'))
           WHERE company_id = ? AND status NOT IN ('applied', 'rejected', 'stale')
           AND last_seen_at < ?""",
        (company_id, cutoff),
    )
    conn.commit()
    return cur.rowcount if cur.rowcount is not None else 0



def _run_ats_fetch(conn, company: CompanyConfig, company_id: int, adapter, run_time: datetime.datetime) -> ScoutResult:
    """Shared after-fetch bookkeeping for any ATSAdapter -- a REGISTRY
    singleton or a per-company CustomAPIAdapter, doesn't matter which:
    upsert postings, stamp last_checked_at, mark stale postings. Pulled
    out so the new custom_api dispatch branch (see run_scout(), added
    2026-08-15 per the 'wire CustomAPIAdapter into Scout's dispatch'
    handoff item) reuses this instead of duplicating it next to the
    REGISTRY branch.

    `company.ats_slug or company.name` is passed to fetch_postings() even
    for a CustomAPIAdapter, which ignores it (its own docstring: accepted
    only to satisfy ATSAdapter's shared interface, since a bound
    CustomAPIConfig already has the real URL) -- keeping the same call
    shape for every adapter means this helper doesn't need to know or
    care which kind it was handed.
    """
    postings = adapter.fetch_postings(company.ats_slug or company.name)
    new_count = _upsert_postings(conn, company_id, postings)
    conn.execute(
        "UPDATE companies SET last_checked_at = ? WHERE id = ?",
        (run_time.isoformat(), company_id),
    )
    conn.commit()
    _mark_stale_postings(conn, company_id, run_time)
    return ScoutResult(company.name, "ats", new_count, len(postings))


def run_scout(
    limiter: RateLimiter | None = None,
    db_path: str | None = None,
    on_company_done: Callable[[ScoutResult], None] | None = None,
) -> list[ScoutResult]:
    """One Scout pass over every active company in the registry.

    Returns per-company results for the caller (Captain, or the CLI) to log
    to run_log and surface any errors -- per ADR-0001, a failed ATS/scrape
    call should be flagged, not silently swallowed.

    `db_path` lets tests point at an isolated tmp db instead of the shared
    data/biohunter.db file.

    `on_company_done`, added to close the dashboard's own documented gap
    (dashboard.py's _run_scout_job() previously couldn't report real
    per-company progress because this function gave it nothing to hook
    into): called once per company, right after that company's
    ScoutResult is appended to `results` below -- same company, same
    result object, no separate bookkeeping. Optional and keyword-only in
    spirit (though not enforced positionally, to avoid breaking any
    existing positional call) so every existing caller (cmd_run_scout,
    tests) keeps working with zero changes. Exceptions raised inside the
    callback are NOT caught here -- a broken progress callback should be
    visible immediately, not silently swallowed the way a single
    company's own fetch failure already is (see the try/except below,
    which is deliberately scoped to fetch/parse work only).
    """
    limiter = limiter or RateLimiter()
    conn = get_connection(db_path)
    init_schema(conn)

    results: list[ScoutResult] = []
    for company in load_companies():
        company_id = _get_or_create_company_id(conn, company)
        run_time = datetime.datetime.now(datetime.timezone.utc)
        try:
            if company.ats_type and company.ats_type in REGISTRY:
                adapter = REGISTRY[company.ats_type]
                limiter.wait_for_domain(company.careers_url)
                result = _run_ats_fetch(conn, company, company_id, adapter, run_time)
                results.append(result)
                if on_company_done:
                    on_company_done(result)

            elif company.ats_type == "custom_api":
                # Per the 2026-08-15 handoff: CustomAPIAdapter is deliberately
                # NOT in ats/__init__.py's REGISTRY, because (unlike the six
                # platform adapters) it isn't a stateless singleton -- every
                # company's URL/pagination/field-mapping is completely
                # different, not just a slug substitution. So it's built
                # fresh per company here, from its config/custom_apis.yaml
                # entry, instead of a REGISTRY lookup. load_custom_api_config()
                # fails loudly (ValueError) on a missing/malformed entry --
                # deliberately not caught here specifically, it falls through
                # to the same broad except Exception below as any other
                # company's fetch/parse failure, and surfaces as a normal
                # ScoutResult(strategy="error"), not a crash.
                config = load_custom_api_config(company.name)
                adapter = CustomAPIAdapter(config, limiter=limiter)
                limiter.wait_for_domain(company.careers_url)
                result = _run_ats_fetch(conn, company, company_id, adapter, run_time)
                results.append(result)
                if on_company_done:
                    on_company_done(result)

            else:
                if not company.css_selector:
                    result = ScoutResult(
                        company.name, "error", 0, 0,
                        error="No ats_type and no css_selector configured -- "
                              "add one to companies.yaml before Scout can monitor this company.",
                    )
                    results.append(result)
                    if on_company_done:
                        on_company_done(result)
                    continue

                html = scraper.fetch_page(company.careers_url, limiter)
                row = conn.execute(
                    "SELECT last_hash FROM companies WHERE id = ?", (company_id,)
                ).fetchone()
                previous_hash = row[0] if row else None
                changed, new_hash = scraper.check_for_change(html, previous_hash)

                new_count = 0
                if changed:
                    postings = scraper.extract_postings(html, company.css_selector, company.careers_url)
                    new_count = _upsert_postings(conn, company_id, postings)
                    if not postings:
                        result = ScoutResult(
                            company.name, "error", 0, 0,
                            error="Page content changed but css_selector matched zero "
                                  "listings -- selector likely needs manual review.",
                        )
                        results.append(result)
                        if on_company_done:
                            on_company_done(result)
                        continue

                conn.execute(
                    "UPDATE companies SET last_checked_at = ?, last_hash = ? WHERE id = ?",
                    (run_time.isoformat(), new_hash, company_id),
                )
                conn.commit()
                _mark_stale_postings(conn, company_id, run_time)
                result = ScoutResult(company.name, "scrape", new_count, new_count)
                results.append(result)
                if on_company_done:
                    on_company_done(result)

        except Exception as exc:  # noqa: BLE001 -- intentionally broad: one company's
            # failure (network error, HTTP error, parse error) must not abort the whole run.
            result = ScoutResult(company.name, "error", 0, 0, error=str(exc))
            results.append(result)
            if on_company_done:
                on_company_done(result)

    return results
