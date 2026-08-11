"""One-off diagnostic: isolates posting 622 exactly (no title/location
filter matching, so no risk of touching other rows) and prints the raw
LLM response BEFORE parse_score() ever sees it. Run from the project
root with the venv active:

    python debug_posting_622.py

Does NOT write to the DB -- read-only on postings, no UPDATE/commit --
so it's safe to run as many times as needed without side effects.
"""
import logging

logging.basicConfig(level=logging.DEBUG, format="%(message)s")

from biohunter.config import load_search_criteria
from biohunter.db import get_connection, init_schema
from biohunter.llm import LLMClient
from biohunter.scorer import score_posting

POSTING_ID = 622

conn = get_connection()
init_schema(conn)

row = conn.execute(
    """SELECT companies.name, postings.title, postings.location, postings.description
       FROM postings JOIN companies ON postings.company_id = companies.id
       WHERE postings.id = ?""",
    (POSTING_ID,),
).fetchone()

if row is None:
    print(f"No posting with id={POSTING_ID}")
else:
    company, title, location, description = row
    print(f"--- Posting {POSTING_ID}: {company} / {title} / {location} ---")
    print(f"Description length: {len(description) if description else 0} chars")
    if not description:
        print("No description stored -- this alone would explain a bad score "
              "(scoring against an empty prompt), but cmd_score_postings' own "
              "skip-if-no-description check should have caught that. Worth "
              "checking why this row got scored at all if description is empty.")
    else:
        criteria = load_search_criteria()
        client = LLMClient()
        result = score_posting(client, company, title, location, description, criteria, think=False)
        print(f"\nparse_score() result: score={result.score}, rationale={result.rationale!r}")
