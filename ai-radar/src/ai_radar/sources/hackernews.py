"""Hacker News source — trending AI/dev news & discussion via the Algolia Search API.

Free, no API key, dated. Good for surfacing what the engineering community is discussing
right now around a topic.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse

from .. import net
from ..config import load_feeds
from ..models import FetchParams, SourceItem
from ..textutil import clean_text
from .base import ContentUnavailable, Source

API = "http://hn.algolia.com/api/v1/search_by_date"


class HackerNewsSource(Source):
    name = "hackernews"

    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_feeds().get("hackernews", {})

    def discover(self, params: FetchParams) -> list[SourceItem]:
        tags = self.config.get("tags", "story")
        q = {
            "query": params.topic,
            "tags": tags,
            "hitsPerPage": str(max(1, params.max_results)),
        }
        filters = []
        since_ts = _since_unix(params.since)
        if since_ts is not None:
            filters.append(f"created_at_i>{since_ts}")
        until_ts = _since_unix(params.until)
        if until_ts is not None:
            filters.append(f"created_at_i<{until_ts}")
        points_min = int(self.config.get("points_min", 0) or 0)
        if points_min > 0:
            filters.append(f"points>={points_min}")
        if filters:
            q["numericFilters"] = ",".join(filters)

        url = f"{API}?{urllib.parse.urlencode(q)}"
        try:
            raw = net.get(url)
            data = json.loads(raw)
        except (net.HTTPError, net.URLError, OSError, json.JSONDecodeError):
            return []

        items: list[SourceItem] = []
        for hit in data.get("hits", []):
            object_id = str(hit.get("objectID", ""))
            title = hit.get("title") or hit.get("story_title") or ""
            story_text = clean_text(hit.get("story_text") or hit.get("comment_text") or "")
            external_url = hit.get("url")
            discussion_url = f"https://news.ycombinator.com/item?id={object_id}"
            items.append(
                SourceItem(
                    source=self.name,
                    external_id=object_id,
                    url=external_url or discussion_url,
                    title=title or None,
                    author=hit.get("author"),
                    publish_date=(hit.get("created_at") or "")[:10] or None,
                    content_type="discussion",
                    meta={
                        "points": hit.get("points"),
                        "num_comments": hit.get("num_comments"),
                        "discussion_url": discussion_url,
                        "story_text": story_text,
                        "link": external_url,
                    },
                )
            )
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        # Body = title + any self-text only; the link/discussion URLs live in meta/url,
        # not stuffed into the content (keeps summaries clean).
        meta = item.meta or {}
        parts = [item.title or ""]
        if meta.get("story_text"):
            parts.append(meta["story_text"])
        text = "\n\n".join(p for p in parts if p).strip()
        if not text:
            raise ContentUnavailable(f"empty HN item {item.external_id}")
        return text, None


def _since_unix(since: str | None) -> int | None:
    if not since:
        return None
    try:
        d = dt.datetime.strptime(since[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp())
    except ValueError:
        return None
