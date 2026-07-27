from __future__ import annotations

import abc
import dataclasses


@dataclasses.dataclass
class RawPosting:
    """Normalized posting shape every ATS adapter (and the fallback scraper) returns."""
    title: str
    url: str
    location: str | None = None
    description: str | None = None


class ATSAdapter(abc.ABC):
    """One adapter per ATS platform. Each wraps that platform's public JSON API."""

    name: str

    @abc.abstractmethod
    def fetch_postings(self, ats_slug: str) -> list[RawPosting]:
        """Return all currently-listed postings for the given company slug.

        Raises requests.HTTPError / requests.ConnectionError on failure --
        callers (Scout) are responsible for retry/backoff and stall-flagging,
        per ADR-0001.
        """
        raise NotImplementedError
