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
