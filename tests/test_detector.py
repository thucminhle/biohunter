import biohunter.scout.detector as detector_module
from biohunter.ats.base import RawPosting
from biohunter.config import CompanyConfig
from biohunter.scout.ratelimit import RateLimiter


class FakeAdapter:
    """Stands in for a real ATS adapter so tests don't hit the network."""

    def __init__(self, postings):
        self._postings = postings

    def fetch_postings(self, ats_slug):
        return self._postings


def test_run_scout_inserts_new_postings_once_and_dedupes_on_rerun(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")

    company = CompanyConfig(
        name="Test Biotech",
        careers_url="https://boards.greenhouse.io/testbiotech",
        ats_type="greenhouse",
        ats_slug="testbiotech",
    )
    monkeypatch.setattr(detector_module, "load_companies", lambda: [company])

    postings = [
        RawPosting(title="Scientist I", url="https://testbiotech.com/jobs/1"),
        RawPosting(title="Research Associate", url="https://testbiotech.com/jobs/2"),
    ]
    monkeypatch.setitem(detector_module.REGISTRY, "greenhouse", FakeAdapter(postings))

    results = detector_module.run_scout(limiter=RateLimiter(min_interval=0), db_path=db_path)
    assert len(results) == 1
    assert results[0].strategy == "ats"
    assert results[0].new_postings == 2
    assert results[0].error is None

    # Second run with identical postings should find zero *new* postings.
    results_again = detector_module.run_scout(limiter=RateLimiter(min_interval=0), db_path=db_path)
    assert results_again[0].new_postings == 0
    assert results_again[0].total_postings == 2


def test_run_scout_marks_old_unseen_postings_as_stale(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")

    company = CompanyConfig(
        name="Test Biotech", careers_url="https://boards.greenhouse.io/testbiotech",
        ats_type="greenhouse", ats_slug="testbiotech",
    )
    monkeypatch.setattr(detector_module, "load_companies", lambda: [company])

    # First run: three postings show up.
    postings = [
        RawPosting(title="Role A (still open)", url="https://testbiotech.com/jobs/a"),
        RawPosting(title="Role B (quietly closed)", url="https://testbiotech.com/jobs/b"),
        RawPosting(title="Role C (already applied)", url="https://testbiotech.com/jobs/c"),
    ]
    monkeypatch.setitem(detector_module.REGISTRY, "greenhouse", FakeAdapter(postings))
    detector_module.run_scout(limiter=RateLimiter(min_interval=0), db_path=db_path)

    # Backdate all three past the 30-day threshold, and mark C as already
    # 'applied' -- to confirm applied postings are protected from staleness.
    import datetime
    conn = detector_module.get_connection(db_path)
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40)).isoformat()
    for url in ("https://testbiotech.com/jobs/a", "https://testbiotech.com/jobs/b", "https://testbiotech.com/jobs/c"):
        conn.execute("UPDATE postings SET last_seen_at = ? WHERE url = ?", (old_time, url))
    conn.execute("UPDATE postings SET status = 'applied' WHERE url = ?", ("https://testbiotech.com/jobs/c",))
    conn.commit()

    # Second run: only Role A still appears in the ATS response (B was
    # quietly removed/filled; C is skipped here too, but is protected anyway).
    monkeypatch.setitem(detector_module.REGISTRY, "greenhouse", FakeAdapter([postings[0]]))
    detector_module.run_scout(limiter=RateLimiter(min_interval=0), db_path=db_path)

    rows = {row[0]: row[1] for row in conn.execute("SELECT url, status FROM postings").fetchall()}
    assert rows["https://testbiotech.com/jobs/a"] == "new"      # re-seen this run -- last_seen_at refreshed
    assert rows["https://testbiotech.com/jobs/b"] == "stale"    # not re-seen, past threshold -- marked stale
    assert rows["https://testbiotech.com/jobs/c"] == "applied"  # protected, never overwritten to stale

def test_run_scout_flags_error_without_aborting_other_companies(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")

    ok_company = CompanyConfig(
        name="Good Co", careers_url="https://boards.greenhouse.io/goodco",
        ats_type="greenhouse", ats_slug="goodco",
    )
    broken_company = CompanyConfig(
        name="No Config Co", careers_url="https://example.com/careers",
        ats_type=None, css_selector=None,
    )
    monkeypatch.setattr(detector_module, "load_companies", lambda: [ok_company, broken_company])
    monkeypatch.setitem(
        detector_module.REGISTRY, "greenhouse",
        FakeAdapter([RawPosting(title="Role", url="https://goodco.com/jobs/1")]),
    )

    results = detector_module.run_scout(limiter=RateLimiter(min_interval=0), db_path=db_path)
    by_name = {r.company_name: r for r in results}

    assert by_name["Good Co"].strategy == "ats"
    assert by_name["Good Co"].new_postings == 1
    assert by_name["No Config Co"].strategy == "error"
    assert "css_selector" in by_name["No Config Co"].error
