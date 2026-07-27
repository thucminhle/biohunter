from __future__ import annotations

import dataclasses
import datetime

from ..ats import REGISTRY
from ..ats.base import RawPosting
from ..config import CompanyConfig, load_companies
from ..db import get_connection, init_schema
from . import scraper
from .ratelimit import RateLimiter


@dataclasses.dataclass
class ScoutResult:
    company_name: str
    strategy: str          # 'ats' | 'scrape' | 'error'
    new_postings: int
    total_postings: int
    error: str | None = None


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
    """Insert new postings, refresh last_seen_at on existing ones. Returns count of new postings."""
    new_count = 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for p in postings:
        existing = conn.execute(
            "SELECT id FROM postings WHERE company_id = ? AND url = ?", (company_id, p.url)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE postings SET last_seen_at = ? WHERE id = ?", (now, existing[0])
            )
        else:
            conn.execute(
                """INSERT INTO postings (company_id, title, url, location, description, status)
                   VALUES (?, ?, ?, ?, ?, 'new')""",
                (company_id, p.title, p.url, p.location, p.description),
            )
            new_count += 1
    conn.commit()
    return new_count


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
        try:
            if company.ats_type and company.ats_type in REGISTRY:
                adapter = REGISTRY[company.ats_type]
                limiter.wait_for_domain(company.careers_url)
                postings = adapter.fetch_postings(company.ats_slug or company.name)
                new_count = _upsert_postings(conn, company_id, postings)
                conn.execute(
                    "UPDATE companies SET last_checked_at = ? WHERE id = ?",
                    (datetime.datetime.now(datetime.timezone.utc).isoformat(), company_id),
                )
                conn.commit()
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
                    (datetime.datetime.now(datetime.timezone.utc).isoformat(), new_hash, company_id),
                )
                conn.commit()
                results.append(ScoutResult(company.name, "scrape", new_count, new_count))

        except Exception as exc:  # noqa: BLE001 -- intentionally broad: one company's
            # failure (network error, HTTP error, parse error) must not abort the whole run.
            results.append(ScoutResult(company.name, "error", 0, 0, error=str(exc)))

    return results
