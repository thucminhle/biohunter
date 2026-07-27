from __future__ import annotations

import dataclasses
import pathlib

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPANIES_YAML = _REPO_ROOT / "config" / "companies.yaml"
_COMPANIES_YAML_EXAMPLE = _REPO_ROOT / "config" / "companies.example.yaml"
_CRITERIA_YAML = _REPO_ROOT / "config" / "search_criteria.yaml"
_CRITERIA_YAML_EXAMPLE = _REPO_ROOT / "config" / "search_criteria.example.yaml"


@dataclasses.dataclass
class SearchCriteria:
    location_include: list[str] = dataclasses.field(default_factory=list)
    location_exclude: list[str] = dataclasses.field(default_factory=list)
    title_include: list[str] = dataclasses.field(default_factory=list)
    title_exclude: list[str] = dataclasses.field(default_factory=list)


def load_search_criteria() -> SearchCriteria:
    """The swappable piece: this file (not any code) is what defines what
    counts as a match for your current search -- location, title keywords,
    etc. Swap this file + companies.yaml to repoint the whole system at a
    different location or job domain."""
    path = _CRITERIA_YAML if _CRITERIA_YAML.exists() else _CRITERIA_YAML_EXAMPLE
    if not _CRITERIA_YAML.exists():
        print(
            f"[config] {_CRITERIA_YAML} not found, using {_CRITERIA_YAML_EXAMPLE.name} "
            "-- copy it to search_criteria.yaml and edit for your actual search."
        )
    data = yaml.safe_load(path.read_text()) or {}
    return SearchCriteria(
        location_include=[s.lower() for s in data.get("location_include", [])],
        location_exclude=[s.lower() for s in data.get("location_exclude", [])],
        title_include=[s.lower() for s in data.get("title_include", [])],
        title_exclude=[s.lower() for s in data.get("title_exclude", [])],
    )


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
