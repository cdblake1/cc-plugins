"""Papers with Code source — papers (often with code links) via the public API (free).

content = title + abstract; code/repo links go in meta. content_type="paper".
"""

from __future__ import annotations

import json
import urllib.parse

from .. import net
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source

API = "https://paperswithcode.com/api/v1/papers/"


class PapersWithCodeSource(Source):
    name = "paperswithcode"

    def discover(self, params: FetchParams) -> list[SourceItem]:
        query = {"q": params.topic, "items_per_page": str(min(50, max(1, params.max_results)))}
        url = f"{API}?{urllib.parse.urlencode(query)}"
        try:
            data = json.loads(net.get(url))
        except (net.HTTPError, net.URLError, OSError, json.JSONDecodeError):
            return []

        items: list[SourceItem] = []
        for p in data.get("results", []) or []:
            abstract = (p.get("abstract") or "").strip()
            title = (p.get("title") or "").strip()
            if not abstract and not title:
                continue
            pub = (p.get("published") or "")[:10] or None
            if params.since and pub and pub < params.since:
                continue
            if params.until and pub and pub >= params.until:
                continue
            items.append(
                SourceItem(
                    source=self.name,
                    external_id=str(p.get("id") or p.get("url_abs") or title),
                    url=p.get("url_abs") or p.get("url_pdf") or "",
                    title=title or None,
                    author=", ".join(p.get("authors", []) or [])[:300] or None,
                    publish_date=pub,
                    content_type="paper",
                    meta={"text": f"{title}\n\n{abstract}".strip()},
                )
            )
            if len(items) >= params.max_results:
                break
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        text = (item.meta or {}).get("text", "").strip()
        if not text:
            raise ContentUnavailable(f"no content for {item.external_id}")
        return text, "en"
