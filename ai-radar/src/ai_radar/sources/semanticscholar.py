"""Semantic Scholar source — research papers via the Graph API (free, no key).

Broadens research coverage beyond arXiv (venues, older work, citation counts). content =
title + abstract; content_type="paper".
"""

from __future__ import annotations

import json
import urllib.parse

from .. import net
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source

API = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,year,authors,url,publicationDate,citationCount,externalIds"


class SemanticScholarSource(Source):
    name = "semanticscholar"

    def discover(self, params: FetchParams) -> list[SourceItem]:
        query = {
            "query": params.topic,
            "limit": str(min(100, max(1, params.max_results))),
            "fields": _FIELDS,
            "sort": "publicationDate:desc",
        }
        url = f"{API}?{urllib.parse.urlencode(query)}"
        try:
            data = json.loads(net.get(url))
        except (net.HTTPError, net.URLError, OSError, json.JSONDecodeError):
            return []

        items: list[SourceItem] = []
        for p in data.get("data", []) or []:
            abstract = (p.get("abstract") or "").strip()
            if not abstract:
                continue
            pub = (p.get("publicationDate") or "")[:10] or (
                f"{p['year']}-01-01" if p.get("year") else None
            )
            if params.since and pub and pub < params.since:
                continue
            if params.until and pub and pub >= params.until:
                continue
            authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:8]) or None
            title = (p.get("title") or "").strip()
            items.append(
                SourceItem(
                    source=self.name,
                    external_id=str(p.get("paperId") or p.get("url") or title),
                    url=p.get("url") or "",
                    title=title or None,
                    author=authors,
                    publish_date=pub,
                    content_type="paper",
                    meta={"text": f"{title}\n\n{abstract}", "citations": p.get("citationCount")},
                )
            )
            if len(items) >= params.max_results:
                break
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        text = (item.meta or {}).get("text", "").strip()
        if not text:
            raise ContentUnavailable(f"no abstract for {item.external_id}")
        return text, "en"
