"""RSS/Atom source — covers BOTH AI news AND key creator/lab blogs.

Reads the curated feed list from feeds.yaml (plus any user additions), fetches each feed
through net.get (so proxy/CA settings apply), and keyword-matches entries against the
topic. Dead/unreachable feeds are skipped silently so one stale URL never breaks a run.
"""

from __future__ import annotations

import re

import feedparser

from .. import net
from ..config import load_feeds
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class RssSource(Source):
    name = "rss"

    def __init__(self, feeds: list[dict] | None = None):
        # Each feed is {"name": ..., "url": ...}. Override allowed for tests.
        self.feeds = feeds if feeds is not None else load_feeds().get("rss_feeds", [])

    def discover(self, params: FetchParams) -> list[SourceItem]:
        topic = params.topic.strip().lower()
        # Channel filter narrows to feeds whose name contains the given substring.
        feeds = self.feeds
        if params.channel:
            needle = params.channel.lower()
            feeds = [f for f in feeds if needle in f.get("name", "").lower()]

        collected: list[SourceItem] = []
        for feed in feeds:
            url = feed.get("url")
            if not url:
                continue
            try:
                raw = net.get(url)
            except (net.HTTPError, net.URLError, OSError):
                continue  # skip dead feed
            parsed = feedparser.parse(raw)
            feed_name = feed.get("name") or parsed.feed.get("title", url)
            for entry in parsed.entries:
                published = _iso_date(entry)
                if params.since and published and published < params.since:
                    continue
                text = _clean(_entry_text(entry))
                title = (entry.get("title") or "").strip()
                if topic and topic not in f"{title} {text}".lower():
                    continue
                if not text:
                    continue
                link = entry.get("link") or entry.get("id") or ""
                collected.append(
                    SourceItem(
                        source=self.name,
                        external_id=link or f"{feed_name}:{title}",
                        url=link,
                        title=title or None,
                        author=entry.get("author") or feed_name,
                        publish_date=published,
                        content_type="article",
                        meta={"feed": feed_name, "text": text},
                    )
                )
        # Newest first, then cap.
        collected.sort(key=lambda i: i.publish_date or "", reverse=True)
        return collected[: params.max_results]

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        text = (item.meta or {}).get("text", "").strip()
        if not text:
            raise ContentUnavailable(f"empty entry for {item.external_id}")
        header = item.title or item.external_id
        return f"{header}\n\n{text}", None


def _entry_text(entry) -> str:
    # Prefer full content when present, else the summary.
    content = entry.get("content")
    if content and isinstance(content, list) and content:
        return content[0].get("value", "") or entry.get("summary", "")
    return entry.get("summary", "") or entry.get("description", "")


def _clean(html: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html or "")).strip()


def _iso_date(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}"
    return None
