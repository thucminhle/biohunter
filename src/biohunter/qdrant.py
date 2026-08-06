from __future__ import annotations

import os

import requests

# TODO: move into config/search_criteria.yaml or similar once there's a
# second thing that needs Qdrant config — not worth a config file for one
# constant yet. Env var lets you override for testing without editing code.
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "resume_content"  # confirmed via seed_qdrant.js — not resume_components


def scroll(filter_: dict, limit: int = 20) -> list[dict]:
    """POST .../points/scroll — same call every "fetch X catalog" node in
    the n8n export makes, just with filter_/limit as parameters instead
    of being hand-written into each node's JSON body 8 times."""
    resp = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
        json={"filter": filter_, "limit": limit, "with_payload": True, "with_vector": False},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]["points"]


def fetch_by_section_type(
    section_type: str | list[str],
    limit: int = 20,
    extra_filter: dict | None = None,
) -> list[dict]:
    """Fetch every point whose payload.section_type matches, returning
    just the payloads (the "points" wrapper — id/vector/payload — never
    mattered to any of the n8n format/select nodes, only payload did).

    section_type can be a single string (most branches) or a list (the
    "always-full sections" branch, which matches career_history OR
    education OR patents OR ... in one call — see n8n's
    match: { any: [...] } shape).

    extra_filter is for the one branch that needs a second condition:
    fetching bullets restricted to a specific set of already-selected
    headings (match: { any: selected_headings } on the "heading" key).
    """
    match = {"any": section_type} if isinstance(section_type, list) else {"value": section_type}
    must = [{"key": "section_type", "match": match}]
    if extra_filter:
        must.append(extra_filter)

    points = scroll({"must": must}, limit=limit)
    return [p["payload"] for p in points]
