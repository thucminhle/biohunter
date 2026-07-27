from biohunter.scout.scraper import check_for_change, extract_postings

SAMPLE_HTML = """
<html><body>
  <div class="jobs">
    <a class="job-listing" href="/jobs/1">Scientist I, Cell Biology</a>
    <a class="job-listing" href="/jobs/2">Research Associate</a>
  </div>
</body></html>
"""


def test_check_for_change_first_run_is_always_changed():
    changed, new_hash = check_for_change(SAMPLE_HTML, previous_hash=None)
    assert changed is True
    assert isinstance(new_hash, str) and len(new_hash) == 64  # sha256 hex digest


def test_check_for_change_detects_identical_content_as_unchanged():
    _, first_hash = check_for_change(SAMPLE_HTML, previous_hash=None)
    changed, second_hash = check_for_change(SAMPLE_HTML, previous_hash=first_hash)
    assert changed is False
    assert first_hash == second_hash


def test_check_for_change_detects_modified_content():
    _, first_hash = check_for_change(SAMPLE_HTML, previous_hash=None)
    modified = SAMPLE_HTML + "<a class='job-listing' href='/jobs/3'>New Role</a>"
    changed, _ = check_for_change(modified, previous_hash=first_hash)
    assert changed is True


def test_extract_postings_finds_listings_and_resolves_relative_urls():
    postings = extract_postings(SAMPLE_HTML, "a.job-listing", base_url="https://example.com/careers")
    assert len(postings) == 2
    assert postings[0].title == "Scientist I, Cell Biology"
    assert postings[0].url == "https://example.com/jobs/1"


def test_extract_postings_returns_empty_list_when_selector_matches_nothing():
    postings = extract_postings(SAMPLE_HTML, "a.nonexistent-class", base_url="https://example.com/careers")
    assert postings == []
