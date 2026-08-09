from __future__ import annotations

import dataclasses
import datetime

from bs4 import BeautifulSoup

from ..ats import REGISTRY
from ..ats.base import RawPosting
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
    conn.commit()
    return new_count


def _mark_stale_postings(conn, company_id: int, run_time: datetime.datetime) -> int:
    """Mark postings not seen in this company's last STALE_AFTER_DAYS worth
    of successful Scout runs as 'stale'. Never touches postings you've
    already progressed (status 'applied' or 'rejected') -- staleness here
    means "no longer visible on the source", not a judgment on postings
    you've already acted on. Returns count of postings newly marked stale.
    """
    cutoff = (run_time - datetime.timedelta(days=STALE_AFTER_DAYS)).isoformat()
    cur = conn.execute(
        """UPDATE postings SET status = 'stale'
           WHERE company_id = ? AND status NOT IN ('applied', 'rejected', 'stale')
           AND last_seen_at < ?""",
        (company_id, cutoff),
    )
    conn.commit()
    return cur.rowcount if cur.rowcount is not None else 0



def run_scout(limiter: RateLimiter | None = None, db_path: str | None = None) -> list[ScoutResult]:
    """One Scout pass over every active company in the registry.

    Returns per-company results for the caller (Captain, or the CLI) to log
    to run_log and surface any errors -- per ADR-0001, a failed ATS/scrape
    call should be flagged, not silently swallowed.

    `db_path` lets tests point at an isolated tmp db instead of the shared
    data/biohunter.db file.
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
                postings = adapter.fetch_postings(company.ats_slug or company.name)
                new_count = _upsert_postings(conn, company_id, postings)
                conn.execute(
                    "UPDATE companies SET last_checked_at = ? WHERE id = ?",
                    (run_time.isoformat(), company_id),
                )
                conn.commit()
                _mark_stale_postings(conn, company_id, run_time)
                results.append(
                    ScoutResult(company.name, "ats", new_count, len(postings))
                )

            else:
                if not company.css_selector:
                    results.append(
                        ScoutResult(
                            company.name, "error", 0, 0,
                            error="No ats_type and no css_selector configured -- "
                                  "add one to companies.yaml before Scout can monitor this company.",
                        )
                    )
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
                        results.append(
                            ScoutResult(
                                company.name, "error", 0, 0,
                                error="Page content changed but css_selector matched zero "
                                      "listings -- selector likely needs manual review.",
                            )
                        )
                        continue

                conn.execute(
                    "UPDATE companies SET last_checked_at = ?, last_hash = ? WHERE id = ?",
                    (run_time.isoformat(), new_hash, company_id),
                )
                conn.commit()
                _mark_stale_postings(conn, company_id, run_time)
                results.append(ScoutResult(company.name, "scrape", new_count, new_count))

        except Exception as exc:  # noqa: BLE001 -- intentionally broad: one company's
            # failure (network error, HTTP error, parse error) must not abort the whole run.
            results.append(ScoutResult(company.name, "error", 0, 0, error=str(exc)))

    return results
