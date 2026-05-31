"""Per-source tests. All network access is monkeypatched; no real requests are made."""

from __future__ import annotations

import sys
import types

import pytest

from ai_radar.models import FetchParams, SourceItem
from ai_radar.sources.base import ContentUnavailable

# --- arXiv -----------------------------------------------------------------

ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2605.00001v1</id>
    <title>Agentic Coding Survey</title>
    <summary>We survey agentic coding methods.</summary>
    <published>2026-05-20T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2605.00001v1"/>
    <author><name>Jane Doe</name></author>
    <category term="cs.AI"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2601.00002v1</id>
    <title>Old Paper</title>
    <summary>Older work.</summary>
    <published>2026-01-01T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2601.00002v1"/>
    <author><name>John Roe</name></author>
    <category term="cs.LG"/>
  </entry>
</feed>"""


def test_arxiv_discover_and_since_filter(monkeypatch):
    from ai_radar.sources import arxiv

    monkeypatch.setattr(arxiv.net, "get", lambda url, **kw: ARXIV_ATOM)
    src = arxiv.ArxivSource(categories=["cs.AI"])
    items = src.discover(FetchParams(topic="agentic coding", since="2026-05-01", max_results=10))

    assert len(items) == 1  # old paper filtered out by since
    item = items[0]
    assert item.external_id == "2605.00001v1"
    assert item.content_type == "paper"
    text, lang = src.fetch_content(item)
    assert "survey agentic coding" in text and lang == "en"


# --- RSS -------------------------------------------------------------------

RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>TestFeed</title>
<item><title>Agentic coding is great</title><link>http://x/1</link>
<description>All about agentic coding workflows.</description>
<pubDate>Wed, 20 May 2026 00:00:00 GMT</pubDate></item>
<item><title>Unrelated cooking post</title><link>http://x/2</link>
<description>Recipes and food.</description>
<pubDate>Wed, 20 May 2026 00:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_discover_filters_by_topic(monkeypatch):
    from ai_radar.sources import rss

    monkeypatch.setattr(rss.net, "get", lambda url, **kw: RSS_XML)
    src = rss.RssSource(feeds=[{"name": "TestFeed", "url": "http://x/feed"}])
    items = src.discover(FetchParams(topic="agentic", max_results=10))

    assert len(items) == 1
    assert items[0].title == "Agentic coding is great"
    text, _ = src.fetch_content(items[0])
    assert "agentic coding workflows" in text


def test_rss_skips_dead_feed(monkeypatch):
    from ai_radar.sources import rss

    def boom(url, **kw):
        raise rss.net.URLError("dead")

    monkeypatch.setattr(rss.net, "get", boom)
    src = rss.RssSource(feeds=[{"name": "Dead", "url": "http://x/dead"}])
    assert src.discover(FetchParams(topic="anything")) == []


# --- Hacker News -----------------------------------------------------------

HN_JSON = (
    b'{"hits":[{"objectID":"111","title":"Agentic coding tools",'
    b'"url":"http://x/post","author":"pg","points":42,"num_comments":10,'
    b'"created_at":"2026-05-20T00:00:00Z","story_text":null}]}'
)


def test_hackernews_discover_and_content(monkeypatch):
    from ai_radar.sources import hackernews

    monkeypatch.setattr(hackernews.net, "get", lambda url, **kw: HN_JSON)
    src = hackernews.HackerNewsSource(config={"tags": "story", "points_min": 0})
    items = src.discover(FetchParams(topic="agentic coding", max_results=5))

    assert len(items) == 1
    item = items[0]
    assert item.external_id == "111" and item.content_type == "discussion"
    text, _ = src.fetch_content(item)
    assert "Agentic coding tools" in text and "Discussion:" in text


# --- YouTube ---------------------------------------------------------------

class _FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL used as a context manager."""

    info = {"entries": [{"id": "vid123", "title": "AI talk", "uploader": "Chan",
                         "upload_date": "20260520", "url": "http://yt/vid123"}]}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, target, download=False):
        return self.info


def _install_fake_yt_dlp(monkeypatch, ydl_cls=_FakeYDL):
    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = ydl_cls
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)


def test_youtube_discover(monkeypatch):
    from ai_radar.sources import youtube

    _install_fake_yt_dlp(monkeypatch)
    src = youtube.YouTubeSource()
    items = src.discover(FetchParams(topic="ai agents", max_results=5))
    assert len(items) == 1
    assert items[0].external_id == "vid123" and items[0].publish_date == "2026-05-20"


def test_youtube_transcript_api_path(monkeypatch):
    from ai_radar.sources import youtube

    api_mod = types.ModuleType("youtube_transcript_api")

    class FakeAPI:
        @staticmethod
        def get_transcript(video_id):
            return [{"text": "hello"}, {"text": "world"}]

    api_mod.YouTubeTranscriptApi = FakeAPI
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", api_mod)

    src = youtube.YouTubeSource()
    item = SourceItem(source="youtube", external_id="vid123", url="http://yt/vid123")
    text, lang = src.fetch_content(item)
    assert text == "hello world" and lang == "en"


def test_youtube_content_unavailable(monkeypatch):
    from ai_radar.sources import youtube

    # transcript api raises -> None; yt-dlp returns no captions -> None -> ContentUnavailable
    api_mod = types.ModuleType("youtube_transcript_api")

    class FakeAPI:
        @staticmethod
        def get_transcript(video_id):
            raise RuntimeError("disabled")

    api_mod.YouTubeTranscriptApi = FakeAPI
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", api_mod)

    class NoCapsYDL(_FakeYDL):
        info = {"subtitles": {}, "automatic_captions": {}}

    _install_fake_yt_dlp(monkeypatch, NoCapsYDL)

    src = youtube.YouTubeSource()
    item = SourceItem(source="youtube", external_id="vid123", url="http://yt/vid123")
    with pytest.raises(ContentUnavailable):
        src.fetch_content(item)
