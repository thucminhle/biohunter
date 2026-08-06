"""
Isolated endpoint-parity test -- NOT part of the BioHunter pipeline.

Purpose: measure whether the timeout the Writer pipeline hit on
select_skills() is caused by WHICH Ollama endpoint gets called --
native /api/chat (what n8n's HTTP Request nodes actually hit) vs the
OpenAI-compatible /v1/chat/completions shim (what OpenAICompatibleClient
in llm.py currently uses) -- and/or by the `think` flag n8n always sends
explicitly but our port currently omits entirely.

This script does NOT import or modify selection.py, writer.py, llm.py,
or roles.yaml. It builds the real skills-selection prompt itself (same
instruction text, same live Qdrant catalog fetch, same job description
you pass in) and fires it at both endpoints under three `think`
conditions each, timing every call with a generous 600s ceiling so a
genuinely slow call gets measured rather than cut off early.

6 sequential large-prompt LLM calls -- this can take a while in the
worst case. A status line prints before each call starts, so it won't
look stuck; Ctrl-C any time if one run is clearly taking far too long
and you want to bail early -- the earlier results already printed are
still useful on their own.

Usage (run in the venv, from the project root):
    python endpoint_parity_test.py --model gemma4:12b-mlx \\
        --job-description-file /Users/thucle/Documents/JOBS/GuardantHealth.md

Swap --model to test a different tag (e.g. qwen3.5:4b-mlx) without
touching roles.yaml.
"""
from __future__ import annotations

import argparse
import time

import requests

from biohunter import qdrant

OLLAMA_HOST = "http://localhost:11434"
CLIENT_TIMEOUT = 600  # generous ceiling for THIS measurement script only -- not a pipeline change

# Copied verbatim from selection.py's SKILLS_INSTRUCTION + select_skills()'s
# prompt assembly. Deliberately copied, not imported -- keeps this script
# fully decoupled from pipeline code so it measures today's real prompt
# shape without being able to silently drift alongside future edits to
# selection.py (or mask a future edit there) without you noticing.
SKILLS_INSTRUCTION = (
    "You are selecting the individual Key Skills bullets most relevant to this job "
    "description, from the flat catalog below. Copy selected items VERBATIM -- do "
    "not edit, merge, or invent. Do not pull in unrelated skills just because they "
    "share a category with a relevant one."
)


def build_skills_prompt(job_description: str) -> tuple[str, int]:
    payloads = qdrant.fetch_by_section_type("key_skills", limit=50)
    skills = [p.get("text", "") for p in payloads]
    catalog_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(skills))
    prompt = (
        f"{SKILLS_INSTRUCTION} "
        'Respond with ONLY valid JSON, no markdown code fences, no other text, '
        'in this exact shape: {"selected_skills": ["<verbatim skill text>", ...]}.'
        f"\n\nJob description:\n{job_description}"
        f"\n\nSkills catalog:\n{catalog_text}"
    )
    return prompt, len(payloads)


def _post(url: str, model: str, prompt: str, think: bool | None, parse_choices: bool) -> tuple[float, str, str | None]:
    body = {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}]}
    if think is not None:
        body["think"] = think

    start = time.monotonic()
    try:
        resp = requests.post(url, json=body, timeout=CLIENT_TIMEOUT)
        elapsed = time.monotonic() - start
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"] if parse_choices else data.get("message", {}).get("content", "")
        return elapsed, content, None
    except Exception as exc:  # noqa: BLE001 - measurement script wants to see every failure mode, not just crash
        elapsed = time.monotonic() - start
        return elapsed, "", f"{type(exc).__name__}: {exc}"


def call_native(model: str, prompt: str, think: bool | None) -> tuple[float, str, str | None]:
    """POST to Ollama's native /api/chat -- matches n8n's HTTP Request node exactly."""
    return _post(f"{OLLAMA_HOST}/api/chat", model, prompt, think, parse_choices=False)


def call_compat(model: str, prompt: str, think: bool | None) -> tuple[float, str, str | None]:
    """POST to Ollama's OpenAI-compatible /v1/chat/completions -- matches
    what OpenAICompatibleClient.chat() currently does."""
    return _post(f"{OLLAMA_HOST}/v1/chat/completions", model, prompt, think, parse_choices=True)


CONDITIONS: list[tuple[str, bool | None]] = [
    ("think omitted (current Python behavior)", None),
    ("think=false (explicit, matches n8n 'Fast')", False),
    ("think=true (explicit, matches n8n 'Thorough')", True),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Ollama model tag, e.g. gemma4:12b-mlx")
    parser.add_argument("--job-description-file", required=True, help="Path to a real job description file")
    args = parser.parse_args()

    with open(args.job_description_file, encoding="utf-8") as f:
        job_description = f.read().strip()

    prompt, n_skills = build_skills_prompt(job_description)
    print(f"Built real skills-selection prompt: {n_skills} catalog entries, {len(prompt)} chars.")
    print(f"Model: {args.model}   Client-side ceiling: {CLIENT_TIMEOUT}s per call\n")

    rows: list[tuple[str, str, float, str]] = []

    for endpoint_label, fn in (("native /api/chat", call_native), ("compat /v1/chat/completions", call_compat)):
        for think_label, think in CONDITIONS:
            print(f"-> running: {endpoint_label} | {think_label} ...", flush=True)
            elapsed, content, error = fn(args.model, prompt, think)
            result = f"ERROR: {error}" if error else f"{len(content)} chars back"
            print(f"   {elapsed:.1f}s -- {result}\n")
            rows.append((endpoint_label, think_label, elapsed, result))

    print("=" * 100)
    print(f"{'Endpoint':<28} {'think':<45} {'Elapsed':>10}  Result")
    print("-" * 100)
    for endpoint_label, think_label, elapsed, result in rows:
        print(f"{endpoint_label:<28} {think_label:<45} {elapsed:>9.1f}s  {result}")


if __name__ == "__main__":
    main()
