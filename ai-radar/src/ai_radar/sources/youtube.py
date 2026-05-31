"""YouTube source — video transcripts, free and no API key.

Discovery uses yt-dlp's flat search (fast, metadata-only). Captions are pulled via
youtube-transcript-api first (lightest), falling back to yt-dlp's caption URLs parsed as
VTT. Both heavy deps are imported lazily so importing this module is cheap and tests can
monkeypatch the imports.
"""

from __future__ import annotations

import re

from .. import net
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source


class YouTubeSource(Source):
    name = "youtube"

    def _ydl_opts(self, **extra) -> dict:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        proxy = net.proxy_url()
        if proxy:
            opts["proxy"] = proxy
        opts.update(extra)
        return opts

    def discover(self, params: FetchParams) -> list[SourceItem]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            return []

        if params.channel:
            target = params.channel if params.channel.startswith("http") else (
                f"https://www.youtube.com/{params.channel}/videos"
            )
        else:
            target = f"ytsearch{max(1, params.max_results)}:{params.topic}"

        opts = self._ydl_opts(extract_flat=True)
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target, download=False)
        except Exception:
            return []

        entries = (info or {}).get("entries") or []
        items: list[SourceItem] = []
        for entry in entries:
            if not entry:
                continue
            vid = entry.get("id")
            if not vid:
                continue
            publish_date = _iso_from_yt(entry.get("upload_date"))
            if params.since and publish_date and publish_date < params.since:
                continue
            if params.until and publish_date and publish_date >= params.until:
                continue
            items.append(
                SourceItem(
                    source=self.name,
                    external_id=vid,
                    url=entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
                    title=entry.get("title"),
                    author=entry.get("uploader") or entry.get("channel"),
                    publish_date=publish_date,
                    content_type="transcript",
                    meta={"duration": entry.get("duration")},
                )
            )
            if len(items) >= params.max_results:
                break
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        lang = "en"
        text = self._via_transcript_api(item.external_id)
        if text:
            return text, lang
        text = self._via_ytdlp_captions(item.external_id)
        if text:
            return text, lang
        raise ContentUnavailable(f"no captions for video {item.external_id}")

    # --- caption strategies ------------------------------------------------

    def _via_transcript_api(self, video_id: str) -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return None
        try:
            segments = YouTubeTranscriptApi.get_transcript(video_id)
        except Exception:
            return None
        text = " ".join(seg.get("text", "") for seg in segments)
        return _collapse(text) or None

    def _via_ytdlp_captions(self, video_id: str) -> str | None:
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            return None
        opts = self._ydl_opts(writesubtitles=True, writeautomaticsub=True)
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=False
                )
        except Exception:
            return None

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
