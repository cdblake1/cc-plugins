from __future__ import annotations

import sys
import types

from ai_radar.models import FetchParams, SourceItem


# --- GitHub ----------------------------------------------------------------

GH_JSON = (
    b'{"items":[{"id":42,"full_name":"acme/agent","description":"An autonomous coding agent",'
    b'"html_url":"https://github.com/acme/agent","language":"Python","stargazers_count":1234,'
    b'"topics":["agents","llm"],"owner":{"login":"acme"},"created_at":"2026-05-20T00:00:00Z"}]}'
)


def test_github_discover_and_content(monkeypatch):
    from ai_radar.sources import github

    monkeypatch.setattr(github.net, "get", lambda url, **kw: GH_JSON)
    src = github.GitHubSource()
    items = src.discover(FetchParams(topic="coding agent", max_results=5))
    assert len(items) == 1 and items[0].content_type == "repo"
    text, _ = src.fetch_content(items[0])
    assert "acme/agent" in text and "autonomous coding agent" in text


def test_github_handles_error(monkeypatch):
    from ai_radar.sources import github

    def boom(url, **kw):
        raise github.net.URLError("rate limited")

    monkeypatch.setattr(github.net, "get", boom)
    assert github.GitHubSource().discover(FetchParams(topic="x")) == []


# --- Semantic Scholar ------------------------------------------------------

S2_JSON = (
    b'{"data":[{"paperId":"p1","title":"Scaling agents","abstract":"We scale agents to N tasks.",'
    b'"publicationDate":"2026-05-15","authors":[{"name":"A. Researcher"}],'
    b'"url":"https://semanticscholar.org/p1","citationCount":3}]}'
)


def test_semanticscholar_discover_since_filter(monkeypatch):
    from ai_radar.sources import semanticscholar

    monkeypatch.setattr(semanticscholar.net, "get", lambda url, **kw: S2_JSON)
    src = semanticscholar.SemanticScholarSource()
    items = src.discover(FetchParams(topic="agents", since="2026-05-01", max_results=5))
    assert len(items) == 1 and items[0].content_type == "paper"
    # filtered out by since
    assert src.discover(FetchParams(topic="agents", since="2026-06-01")) == []
    text, lang = src.fetch_content(items[0])
    assert "scale agents" in text and lang == "en"


# --- Papers with Code ------------------------------------------------------

PWC_JSON = (
    b'{"results":[{"id":"pwc1","title":"Code agents","abstract":"Agents that write code.",'
    b'"published":"2026-05-10","url_abs":"https://paperswithcode.com/paper/pwc1"}]}'
)


def test_paperswithcode_discover(monkeypatch):
    from ai_radar.sources import paperswithcode

    monkeypatch.setattr(paperswithcode.net, "get", lambda url, **kw: PWC_JSON)
    src = paperswithcode.PapersWithCodeSource()
    items = src.discover(FetchParams(topic="code agents", max_results=5))
    assert len(items) == 1
    text, _ = src.fetch_content(items[0])
    assert "Agents that write code" in text


# --- arXiv full-text -------------------------------------------------------

ARXIV_HTML = b"<html><body><h1>Title</h1>" + b"<p>Detailed findings paragraph. </p>" * 200 + b"</body></html>"


def test_arxiv_prefers_fulltext(monkeypatch):
    from ai_radar.sources import arxiv

    monkeypatch.setattr(arxiv.net, "get", lambda url, **kw: ARXIV_HTML)
    src = arxiv.ArxivSource(categories=["cs.AI"], fetch_fulltext=True)
    item = SourceItem(source="arxiv", external_id="2605.00001v1", url="http://x",
                      title="T", content_type="paper", meta={"abstract": "short abstract"})
    text, lang = src.fetch_content(item)
    assert "Detailed findings paragraph" in text and lang == "en"
    assert len(text) > len("short abstract") * 2


def test_arxiv_falls_back_to_abstract(monkeypatch):
    from ai_radar.sources import arxiv

    def boom(url, **kw):
        raise arxiv.net.URLError("no html")

    monkeypatch.setattr(arxiv.net, "get", boom)
    src = arxiv.ArxivSource(categories=["cs.AI"], fetch_fulltext=True)
    item = SourceItem(source="arxiv", external_id="2605.00002v1", url="http://x",
                      title="T2", content_type="paper", meta={"abstract": "the abstract"})
    text, _ = src.fetch_content(item)
    assert "the abstract" in text


# --- YouTube description fallback ------------------------------------------

class _FallbackYDL:
    """extract_info returns metadata with a description but no captions."""

    info = {"title": "Deep dive into agents", "description": "This video explains AI agents in depth.",
            "subtitles": {}, "automatic_captions": {}}

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, target, download=False):
        return self.info


def test_youtube_description_fallback(monkeypatch):
    from ai_radar.sources import youtube

    api_mod = types.ModuleType("youtube_transcript_api")

    class FakeAPI:
        @staticmethod
        def get_transcript(video_id):
            raise RuntimeError("blocked on CI IP")

    api_mod.YouTubeTranscriptApi = FakeAPI
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", api_mod)

    ydl_mod = types.ModuleType("yt_dlp")
    ydl_mod.YoutubeDL = _FallbackYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", ydl_mod)

    src = youtube.YouTubeSource(channels=[])
    item = SourceItem(source="youtube", external_id="vid1", url="http://yt/vid1",
                      title="Deep dive into agents", content_type="transcript")
    text, lang = src.fetch_content(item)
    assert "explains AI agents" in text
    assert item.content_type == "video"  # marked metadata-only, not a transcript


# --- YouTube cookies + throttle (ban-safe) ---------------------------------

def test_youtube_no_cookies_by_default(monkeypatch):
    """With nothing configured, yt-dlp opts carry no cookiefile/sleep — behaves as before."""
    from ai_radar.sources import youtube

    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YT_SLEEP_SECONDS", raising=False)
    opts = youtube.YouTubeSource(channels=[])._ydl_opts(extract_flat=True)
    assert "cookiefile" not in opts
    assert "sleep_interval" not in opts and "sleep_interval_requests" not in opts
    assert opts["extract_flat"] is True  # extras still merged


def test_youtube_cookies_and_throttle_applied(monkeypatch, tmp_path):
    """A configured cookies file + sleep land in the yt-dlp opts dict."""
    from ai_radar.sources import youtube

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YT_COOKIES_FILE", str(cookies))
    monkeypatch.setenv("YT_SLEEP_SECONDS", "2")

    opts = youtube.YouTubeSource(channels=[])._ydl_opts(writesubtitles=True)
    assert opts["cookiefile"] == str(cookies)
    assert opts["sleep_interval_requests"] == 2.0 and opts["sleep_interval"] == 2.0


def test_youtube_missing_cookie_path_ignored(monkeypatch):
    """A pointed-but-absent cookies path is ignored rather than passed to yt-dlp."""
    from ai_radar.sources import youtube

    monkeypatch.setenv("YT_COOKIES_FILE", "/no/such/cookies.txt")
    opts = youtube.YouTubeSource(channels=[])._ydl_opts()
    assert "cookiefile" not in opts
