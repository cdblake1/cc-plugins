"""The Source seam: every content source implements this small interface.

The orchestrator (cli.fetch) only ever talks to `Source`, so adding a new source —
podcasts, Semantic Scholar, GitHub trending — means one new module + one registry entry
and nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import FetchParams, SourceItem


class ContentUnavailable(Exception):
    """Raised by fetch_content when an item has no retrievable text (e.g. no captions)."""


class Source(ABC):
    #: short, stable identifier used in --sources and stored on every document row
    name: str = ""

    @abstractmethod
    def discover(self, params: FetchParams) -> list[SourceItem]:
        """Find candidate items for a topic. Cheap metadata only — no full text yet."""
        raise NotImplementedError

    @abstractmethod
    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        """Return (content_text, lang) for an item.

        Raise ContentUnavailable if no text can be retrieved; the orchestrator records a
        skip rather than failing the whole run.
        """
        raise NotImplementedError
