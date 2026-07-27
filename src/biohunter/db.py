"""
DB connection + schema init.

Dev mode (default): plain local SQLite file at data/biohunter.db.
Turso mode: set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars and the
same code becomes an embedded-replica sync'd against your Turso db --
no code changes needed, per libsql-experimental's design.
"""
from __future__ import annotations

import os
import pathlib

import libsql_experimental as libsql

_SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "schema.sql"
_DEFAULT_LOCAL_DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "biohunter.db"


def get_connection(local_path: str | None = None):
    """Return a libsql connection, local-only or Turso-synced depending on env.

    `local_path` overrides the default data/biohunter.db location -- mainly
    for tests (a tmp_path db per test), or set BIOHUNTER_DB_PATH env var for
    a one-off custom location.
    """
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    target = pathlib.Path(local_path or os.environ.get("BIOHUNTER_DB_PATH") or _DEFAULT_LOCAL_DB)
    target.parent.mkdir(parents=True, exist_ok=True)

    if turso_url and turso_token:
        # Embedded replica: local file kept in sync with Turso.
        conn = libsql.connect(str(target), sync_url=turso_url, auth_token=turso_token)
        conn.sync()
        return conn

    return libsql.connect(str(target))


def init_schema(conn) -> None:
    """Apply schema.sql. Safe to call repeatedly (uses CREATE TABLE IF NOT EXISTS)."""
    sql = _SCHEMA_PATH.read_text()
    # libsql's executescript equivalent: split on statement boundaries and
    # run one at a time, since libsql_experimental doesn't expose executescript.
    for statement in _split_statements(sql):
        if statement.strip():
            conn.execute(statement)
    conn.commit()


def _split_statements(sql: str) -> list[str]:
    # Naive but sufficient here: our schema has no semicolons inside strings.
    return [s.strip() for s in sql.split(";") if s.strip()]


if __name__ == "__main__":
    # `python -m biohunter.db` -> initialize the local dev DB.
    conn = get_connection()
    init_schema(conn)
    print(f"Schema applied to {_DEFAULT_LOCAL_DB}")
