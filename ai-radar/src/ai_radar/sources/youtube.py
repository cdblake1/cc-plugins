"""YouTube source — video transcripts, free and no API key.

Discovery uses yt-dlp's flat search (fast, metadata-only). Captions are pulled via
youtube-transcript-api first (lightest), falling back to yt-dlp's caption URLs parsed as
VTT. Both heavy deps are imported lazily so importing this module is cheap and tests can
monkeypatch the imports.
"""

from __future__ import annotations

import os
import re

from .. import net
from ..config import load_feeds
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source


def _cookiefile() -> str | None:
    """Path to a yt-dlp cookies.txt, from YT_COOKIES_FILE, if it exists.

    Use cookies from a DEDICATED THROWAWAY Google account — never a personal one — to clear
    YouTube's "Sign in to confirm you're not a bot" gate on datacenter IPs. If the flagged
    cookie is ever burned, you lose a disposable account, not your real one.
    """
    path = os.environ.get("YT_COOKIES_FILE", "").strip()
    if path and os.path.exists(path):
        return path
    return None


def _sleep_seconds() -> float:
    """Per-request politeness delay (seconds). Throttling is the biggest ban-risk lever."""
    try:
        return max(0.0, float(os.environ.get("YT_SLEEP_SECONDS", "0") or "0"))
    except ValueError:
        return 0.0


class YouTubeSource(Source):
    name = "youtube"

    def __init__(self, channels: list[str] | None = None):
        # Curated channels (handles/URLs/ids) from feeds.yaml; higher-signal than search.
        self.channels = channels if channels is not None else load_feeds().get(
            "youtube_channels", []
        )

    def _ydl_opts(self, **extra) -> dict:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        proxy = net.proxy_url()
        if proxy:
            opts["proxy"] = proxy
        ca = net.ca_bundle_path()
        if ca:  # yt-dlp doesn't read SSL_CERT_FILE the way net.py's urllib opener does.
            opts["ca_certs"] = ca
        cookies = _cookiefile()
        if cookies:
            opts["cookiefile"] = cookies
        sleep = _sleep_seconds()
        if sleep:
            # Rate-limit so cookied traffic looks human, not like a scraper.
            opts["sleep_interval_requests"] = sleep
            opts["sleep_interval"] = sleep
        opts.update(extra)
        return opts

    def discover(self, params: FetchParams) -> list[SourceItem]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            return []

        # Targets: a topic search, plus each curated channel (whose videos we then keep
        # only if the title matches the topic). An explicit --channel overrides both.
        if params.channel:
            targets = [(_channel_url(params.channel), False)]
        else:
            targets = [(f"ytsearch{max(1, params.max_results)}:{params.topic}", False)]
            targets += [(_channel_url(c), True) for c in self.channels]

        topic_terms = [w for w in params.topic.lower().split() if len(w) > 3]
        items: list[SourceItem] = []
        seen: set[str] = set()
        for target, is_channel in targets:
            opts = self._ydl_opts(extract_flat=True, playlistend=max(1, params.max_results))
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(target, download=False)
            except Exception:
                continue
            for entry in (info or {}).get("entries") or []:
                if not entry:
                    continue
                vid = entry.get("id")
                if not vid or vid in seen:
                    continue
                publish_date = _iso_from_yt(entry.get("upload_date"))
                if params.since and publish_date and publish_date < params.since:
                    continue
                if params.until and publish_date and publish_date >= params.until:
                    continue
                title = entry.get("title") or ""
                # For channel back-catalogs, keep only topic-relevant videos.
                if is_channel and topic_terms and not any(t in title.lower() for t in topic_terms):
                    continue
                seen.add(vid)
                items.append(
                    SourceItem(
                        source=self.name,
                        external_id=vid,
                        url=entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
                        title=title or None,
                        author=entry.get("uploader") or entry.get("channel"),
                        publish_date=publish_date,
                        content_type="transcript",
                        meta={"duration": entry.get("duration")},
                    )
                )
                if len(items) >= params.max_results:
                    break
            if len(items) >= params.max_results:
                break
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        lang = "en"
        # 1) transcript via the light API
        text = self._via_transcript_api(item.external_id)
        if text:
            return text, lang
        # 2) one yt-dlp extract: try captions, else fall back to title + description so the
        #    video is still captured even when transcripts are blocked (common on CI IPs).
        info = self._extract(item.external_id)
        if info:
            cap = self._captions_from_info(info)
            if cap:
                return cap, lang
            desc = (info.get("description") or "").strip()
            if desc:
                item.content_type = "video"  # mark depth: metadata only, not a transcript
                title = info.get("title") or item.title or ""
                return f"{title}\n\n{desc}", lang
        raise ContentUnavailable(f"no transcript or description for video {item.external_id}")

    # --- caption strategies ------------------------------------------------

    def _via_transcript_api(self, video_id: str) -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return None
        cookies = _cookiefile()
        try:
            # Pass cookies when supported (signature varies across versions); retry plain.
            if cookies:
                try:
                    segments = YouTubeTranscriptApi.get_transcript(video_id, cookies=cookies)
                except TypeError:
                    segments = YouTubeTranscriptApi.get_transcript(video_id)
            else:
                segments = YouTubeTranscriptApi.get_transcript(video_id)
        except Exception:
            return None
        text = " ".join(seg.get("text", "") for seg in segments)
        return _collapse(text) or None

    def _extract(self, video_id: str) -> dict | None:
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            return None
        opts = self._ydl_opts(writesubtitles=True, writeautomaticsub=True)
        try:
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=False
                )
        except Exception:
            return None

    def _captions_from_info(self, info: dict) -> str | None:
        tracks = {**(info.get("subtitles") or {}), **(info.get("automatic_captions") or {})}
        url = _pick_caption_url(tracks)
        if not url:
            return None
        try:
            raw = net.get(url).decode("utf-8", "replace")
        except (net.HTTPError, net.URLError, OSError):
            return None
        return _parse_vtt(raw) or None


# --- helpers ---------------------------------------------------------------


def _channel_url(channel: str) -> str:
    """Normalize a channel handle/URL/id into a /videos listing URL."""
    if channel.startswith("http"):
        return channel if "/videos" in channel else channel.rstrip("/") + "/videos"
    handle = channel if channel.startswith("@") else channel
    return f"https://www.youtube.com/{handle}/videos"

_TS_RE = re.compile(r"\d\d:\d\d:\d\d[.,]\d\d\d")
_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def _iso_from_yt(upload_date: str | None) -> str | None:
    # yt-dlp upload_date is YYYYMMDD
    if upload_date and len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return None


def _pick_caption_url(tracks: dict) -> str | None:
    # Prefer English; prefer a text-y format (vtt) over json.
    for key in ("en", "en-US", "en-GB"):
        if key in tracks and tracks[key]:
            return _best_format(tracks[key])
    for fmts in tracks.values():
        if fmts:
            return _best_format(fmts)
    return None


def _best_format(formats: list[dict]) -> str | None:
    for fmt in formats:
        if fmt.get("ext") == "vtt":
            return fmt.get("url")
    return formats[0].get("url") if formats else None


def _parse_vtt(vtt: str) -> str:
    lines: list[str] = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        line = _TAG_RE.sub("", line)
        if line:
            lines.append(line)
    # Collapse the rolling-duplicate lines auto-captions love to emit.
    deduped: list[str] = []
    for ln in lines:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)
    return _collapse(" ".join(deduped))


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", _TS_RE.sub("", text or "")).strip()
