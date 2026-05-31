"""arXiv source — research papers / breakthroughs via the public arXiv Atom API.

Free, no API key. Discovery returns paper metadata + abstract in one call, so
fetch_content just returns the abstract already attached during discover().
"""

from __future__ import annotations

import urllib.parse

import feedparser

from .. import net
from ..config import load_feeds
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source

API = "http://export.arxiv.org/api/query"


class ArxivSource(Source):
    name = "arxiv"

    def __init__(self, categories: list[str] | None = None):
        # Default categories come from feeds.yaml; allow override for tests.
        self.categories = categories if categories is not None else load_feeds().get(
            "arxiv_categories", []
        )

    def _build_query(self, params: FetchParams) -> str:
        cat_clause = " OR ".join(f"cat:{c}" for c in self.categories) if self.categories else ""
        topic = params.topic.strip()
        topic_clause = f'all:"{topic}"' if topic else ""
        if cat_clause and topic_clause:
            search = f"({cat_clause}) AND {topic_clause}"
        else:
            search = topic_clause or cat_clause or "all:artificial intelligence"
        q = {
            "search_query": search,
            "start": "0",
            "max_results": str(max(1, params.max_results)),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        return f"{API}?{urllib.parse.urlencode(q)}"

    def discover(self, params: FetchParams) -> list[SourceItem]:
        url = self._build_query(params)
        try:
            raw = net.get(url)
        except (net.HTTPError, net.URLError, OSError):
            return []
        parsed = feedparser.parse(raw)
        items: list[SourceItem] = []
        for entry in parsed.entries:
            published = _iso_date(entry)
            if params.since and published and published < params.since:
                continue
            arxiv_id = _arxiv_id(entry.get("id", ""))
            authors = ", ".join(a.get("name", "") for a in entry.get("authors", [])) or None
            abstract = (entry.get("summary") or "").strip()
            items.append(
                SourceItem(
                    source=self.name,
                    external_id=arxiv_id or entry.get("id", ""),
                    url=entry.get("link", entry.get("id", "")),
                    title=(entry.get("title") or "").strip() or None,
                    author=authors,
                    publish_date=published,
                    content_type="paper",
                    meta={"abstract": abstract, "categories": _categories(entry)},
                )
            )
            if len(items) >= params.max_results:
                break
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        abstract = (item.meta or {}).get("abstract", "").strip()
        if not abstract:
            raise ContentUnavailable(f"no abstract for {item.external_id}")
        header = item.title or item.external_id
        return f"{header}\n\n{abstract}", "en"


def _arxiv_id(entry_id: str) -> str:
    # entry id looks like http://arxiv.org/abs/2401.12345v1
    return entry_id.rsplit("/abs/", 1)[-1] if "/abs/" in entry_id else entry_id


def _iso_date(entry) -> str | None:
    published = entry.get("published") or entry.get("updated")
    if not published:
        return None
    # arXiv uses e.g. 2026-05-20T17:59:59Z; the date prefix is enough for filtering.
    return published[:10]


def _categories(entry) -> list[str]:
    tags = entry.get("tags", []) or []
    return [t.get("term") for t in tags if t.get("term")]
