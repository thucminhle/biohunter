"""
One-off cleanup script: delete a posting (and anything referencing it) by
its stored URL. Useful any time you want a posting fully gone rather than
sitting there marked 'stale' forever -- e.g. re-testing the browser
extension capture on the same LinkedIn posting.

There is currently no delete button in the dashboard itself (only
"mark as stale" exists) -- this script is the only way to actually
remove a row today.

Usage (run from your project root, same folder as schema.sql):
    python3 delete_posting.py "https://www.linkedin.com/jobs/view/4443580788/"

Uses db.py's get_connection() (same real DB connection logic as the rest
of the project, dev-local or Turso depending on your env vars) rather
than a bare sqlite3.connect() -- unlike migrate_add_apply_url.py, which
had to use bare sqlite3 because db.py wasn't available in that session.
"""
import sys

sys.path.insert(0, "src")
from biohunter.db import get_connection  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print('Usage: python3 delete_posting.py "<posting-url>"')
        sys.exit(1)

    url = sys.argv[1].strip()
    conn = get_connection()

    rows = conn.execute(
        "SELECT postings.id, postings.title, postings.status, companies.name "
        "FROM postings JOIN companies ON companies.id = postings.company_id "
        "WHERE postings.url = ?",
        (url,),
    ).fetchall()

    if not rows:
        print(f"No posting found with url = {url!r}. Nothing to delete.")
        return

    print(f"Found {len(rows)} matching posting(s):\n")
    for posting_id, title, status, company in rows:
        print(f"  posting_id={posting_id}  company={company!r}  title={title!r}  status={status!r}")

    confirm = input(
        f"\nDelete {len(rows)} posting(s) above, plus any drafts/applications/"
        "outreach emails tied to them? [y/N] "
    )
    if confirm.strip().lower() != "y":
        print("Cancelled -- nothing deleted.")
        return

    for posting_id, *_ in rows:
        # schema.sql has no ON DELETE CASCADE on these foreign keys, so
        # dependent rows have to be cleared manually first or the delete
        # below would fail (or leave orphans, depending on FK enforcement).
        conn.execute("DELETE FROM drafts WHERE posting_id = ?", (posting_id,))
        conn.execute("DELETE FROM applications WHERE posting_id = ?", (posting_id,))
        conn.execute("DELETE FROM outreach_emails WHERE posting_id = ?", (posting_id,))
        # Clear the self-referential link in case any OTHER posting points
        # at this one as its repost source -- otherwise that row would
        # dangle, pointing at an id that no longer exists.
        conn.execute(
            "UPDATE postings SET reposted_from_id = NULL WHERE reposted_from_id = ?",
            (posting_id,),
        )
        conn.execute("DELETE FROM postings WHERE id = ?", (posting_id,))

    conn.commit()
    print(f"\nDeleted {len(rows)} posting(s).")


if __name__ == "__main__":
    main()
