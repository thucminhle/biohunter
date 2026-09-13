"""
Dashboard presentation settings: which Workspace layout is active, and
(reserved for later) which color palette. Same dashboard-editable
singleton-row pattern as settings_db.py's candidate_settings -- one
module, one concern, kept separate rather than folded into
candidate_settings since these are presentation preferences, not
candidate identity data. See schema.sql's dashboard_settings table.

`palette` only ever holds "default" right now -- the full 10-palette
system (roadmap) is deferred; the field exists so that work won't need
a second migration when it happens.

Same shape as settings_db.py on purpose: a small dataclass, a get, a
save, no ORM.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DashboardSettings:
    layout_mode: str = "master_detail"
    palette: str = "default"


def get_dashboard_settings(conn) -> DashboardSettings:
    """Returns the current settings, or the dataclass defaults if the
    row has never been saved -- same not-yet-configured convention as
    settings_db.get_candidate_settings()."""
    row = conn.execute(
        "SELECT layout_mode, palette FROM dashboard_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return DashboardSettings()
    layout_mode, palette = row
    return DashboardSettings(
        layout_mode=layout_mode or "master_detail",
        palette=palette or "default",
    )


def save_dashboard_settings(conn, layout_mode: str, palette: str) -> None:
    """Upserts the singleton row -- same INSERT ... ON CONFLICT pattern
    as save_candidate_settings()."""
    conn.execute(
        """INSERT INTO dashboard_settings (id, layout_mode, palette, updated_at)
           VALUES (1, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             layout_mode = excluded.layout_mode,
             palette = excluded.palette,
             updated_at = excluded.updated_at""",
        (layout_mode.strip(), palette.strip()),
    )
    conn.commit()
