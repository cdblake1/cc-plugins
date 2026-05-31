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

    def __init__(self, categories: list[str] | None = None, *,
                 fetch_fulltext: bool = True, max_chars: int = 56000):
        # Default categories come from feeds.yaml; allow override for tests.
        self.categories = categories if categories is not None else load_feeds().get(
            "arxiv_categories", []
        )
        self.fetch_fulltext = fetch_fulltext
        self.max_chars = max_chars  # ~16k tokens

    def _build_query(self, params: FetchParams) -> str:
        cat_clause = " OR ".join(f"cat:{c}" for c in self.categories) if self.categories else ""
        topic = params.topic.strip()
        topic_clause = f'all:"{topic}"' if topic else ""
        if cat_clause and topic_clause:
            search = f"({cat_clause}) AND {topic_clause}"
        else:
            search = topic_clause or cat_clause or "all:artificial intelligence"
        # Date-bound the query for windowed backfill (arXiv supports submittedDate ranges).
        date_clause = _submitted_date_clause(params.since, params.until)
        if date_clause:
            search = f"({search}) AND {date_clause}"
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
            if params.until and published and published >= params.until:
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
        header = item.title or item.external_id
        # Prefer full text (arXiv HTML / ar5iv) so summaries capture real findings, not just
        # the abstract. Fall back to the abstract on any failure.
        if self.fetch_fulltext:
            full = self._fetch_html(item.external_id)
            if full and len(full) > len(abstract) * 1.2:
                return f"{header}\n\n{full[: self.max_chars]}", "en"
        if abstract:
            return f"{header}\n\n{abstract}", "en"
        raise ContentUnavailable(f"no content for {item.external_id}")

    def _fetch_html(self, arxiv_id: str) -> str | None:
        from ..textutil import clean_text

        base = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
        for url in (
            f"https://arxiv.org/html/{arxiv_id}",
            f"https://arxiv.org/html/{base}",
            f"https://ar5iv.org/html/{base}",
        ):
            try:
                raw = net.get(url, timeout=30).decode("utf-8", "replace")
            except (net.HTTPError, net.URLError, OSError):
                continue
            text = clean_text(raw)
            if len(text) > 500:
                return text
        return None


def _submitted_date_clause(since: str | None, until: str | None) -> str:
    """arXiv submittedDate range, e.g. submittedDate:[202601010000 TO 202602012359]."""
    if not since and not until:
        return ""
    lo = (since or "1900-01-01").replace("-", "")[:8] + "0000"
    hi = (until or "2999-12-31").replace("-", "")[:8] + "2359"
    return f"submittedDate:[{lo} TO {hi}]"


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
