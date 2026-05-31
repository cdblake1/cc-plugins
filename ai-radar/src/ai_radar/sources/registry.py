"""Maps source names to Source implementations.

Sources are imported lazily inside get_source() so that a missing optional dependency
(e.g. yt-dlp) only matters when that specific source is actually requested.
"""

from __future__ import annotations

from .base import Source

#: canonical order used when --sources all is requested
ALL_SOURCES = [
    "arxiv", "semanticscholar", "paperswithcode", "rss", "hackernews", "github", "youtube",
]


def get_source(name: str) -> Source:
    name = name.strip().lower()
    if name == "arxiv":
        from .arxiv import ArxivSource
        return ArxivSource()
    if name == "semanticscholar":
        from .semanticscholar import SemanticScholarSource
        return SemanticScholarSource()
    if name == "paperswithcode":
        from .paperswithcode import PapersWithCodeSource
        return PapersWithCodeSource()
    if name == "rss":
        from .rss import RssSource
        return RssSource()
    if name == "hackernews":
        from .hackernews import HackerNewsSource
        return HackerNewsSource()
    if name == "github":
        from .github import GitHubSource
        return GitHubSource()
    if name == "youtube":
        from .youtube import YouTubeSource
        return YouTubeSource()
    raise ValueError(f"unknown source: {name!r} (known: {', '.join(ALL_SOURCES)})")


def resolve_sources(spec: str | None) -> list[str]:
    """Turn a --sources value ('all' or 'arxiv,rss') into an ordered list of names."""
    if not spec or spec.strip().lower() == "all":
        return list(ALL_SOURCES)
    names = [s.strip().lower() for s in spec.split(",") if s.strip()]
    for n in names:
        if n not in ALL_SOURCES:
            raise ValueError(f"unknown source: {n!r} (known: {', '.join(ALL_SOURCES)})")
    return names
