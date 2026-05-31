"""Plain data structures shared across the package.

Kept dependency-free (stdlib dataclasses only) so every layer — sources, storage,
summarizers, CLI — can import these without pulling in anything heavy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FetchParams:
    """Parameters for a single fetch, passed to every Source.discover()."""

    topic: str
    since: str | None = None          # ISO date lower bound, e.g. "2026-05-01"
    until: str | None = None          # ISO date upper bound (exclusive), for windowed backfill
    max_results: int = 10             # per-source cap
    channel: str | None = None        # source-specific filter (channel/feed/author)
    lang: str | None = None           # preferred content language (e.g. "en")
    extra: dict = field(default_factory=dict)


@dataclass
class SourceItem:
    """A discovered item before its content/transcript has been fetched."""

    source: str                       # 'arxiv' | 'rss' | 'hackernews' | 'youtube'
    external_id: str                  # stable id within the source
    url: str
    title: str | None = None
    author: str | None = None
    publish_date: str | None = None   # ISO-8601 if known
    content_type: str = "article"     # 'paper' | 'article' | 'discussion' | 'transcript'
    meta: dict = field(default_factory=dict)


@dataclass
class Document:
    """A fetched item with content, ready to persist (mirrors the `documents` table)."""

    source: str
    content_type: str
    external_id: str
    url: str
    topic: str
    content: str
    fetched_at: str
    title: str | None = None
    author: str | None = None
    publish_date: str | None = None
    lang: str | None = None
    meta: dict = field(default_factory=dict)
    run_id: int | None = None
    id: int | None = None


@dataclass
class Run:
    """One `fetch` invocation (mirrors the `runs` table)."""

    topic: str
    sources: str                      # comma-joined source names
    params_json: str
    started_at: str
    id: int | None = None
    finished_at: str | None = None
    item_count: int = 0
    status: str = "running"           # running | ok | error
