from __future__ import annotations

import dataclasses
import pathlib

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPANIES_YAML = _REPO_ROOT / "config" / "companies.yaml"
_COMPANIES_YAML_EXAMPLE = _REPO_ROOT / "config" / "companies.example.yaml"


@dataclasses.dataclass
class CompanyConfig:
    name: str
    careers_url: str
    ats_type: str | None = None
    ats_slug: str | None = None
    css_selector: str | None = None


def load_companies() -> list[CompanyConfig]:
    path = _COMPANIES_YAML if _COMPANIES_YAML.exists() else _COMPANIES_YAML_EXAMPLE
    if not _COMPANIES_YAML.exists():
        print(
            f"[config] {_COMPANIES_YAML} not found, using {_COMPANIES_YAML_EXAMPLE.name} "
            "-- copy it to companies.yaml and add your real target list."
        )

    data = yaml.safe_load(path.read_text()) or {}
    companies = []
    for entry in data.get("companies", []):
        companies.append(
            CompanyConfig(
                name=entry["name"],
                careers_url=entry["careers_url"],
                ats_type=entry.get("ats_type"),
                ats_slug=entry.get("ats_slug"),
                css_selector=entry.get("css_selector"),
            )
        )
    return companies
