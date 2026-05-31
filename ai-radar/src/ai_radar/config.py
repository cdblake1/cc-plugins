"""Configuration: env loading, feeds.yaml, DB path, and the LLM pricing table.

Everything that reads the environment or the filesystem for settings funnels through
here so the rest of the package stays pure and testable.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# --- Paths -----------------------------------------------------------------

_PKG_ROOT = Path(__file__).resolve().parent
# config/feeds.yaml sits next to the project (src/ai_radar/../../config) in the repo,
# and is also shipped as package data; try both.
def _config_candidates(name: str) -> list[Path]:
    return [
        _PKG_ROOT.parent.parent / "config" / name,  # repo / editable install
        _PKG_ROOT / "config" / name,                # packaged copy fallback
    ]


def feeds_path() -> Path:
    """Return the first existing feeds.yaml path (repo layout preferred)."""
    for candidate in _config_candidates("feeds.yaml"):
        if candidate.exists():
            return candidate
    # Default to the repo-layout path even if missing, so errors are legible.
    return _config_candidates("feeds.yaml")[0]


def topics_path() -> Path:
    """Return the first existing topics.yaml path (repo layout preferred)."""
    for candidate in _config_candidates("topics.yaml"):
        if candidate.exists():
            return candidate
    return _config_candidates("topics.yaml")[0]


def load_topics(path: Path | None = None) -> dict:
    """Load topics.yaml for the scheduled digest, with sensible defaults."""
    p = path or topics_path()
    raw: dict = {}
    if p.exists():
        with open(p, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    summarize = dict(raw.get("summarize", {}) or {})
    return {
        "topics": list(raw.get("topics", []) or []),
        "since_days": int(raw.get("since_days", 2) or 2),
        "max_per_source": int(raw.get("max_per_source", 5) or 5),
        "sources": raw.get("sources", "all") or "all",
        "summarize": {
            "mode": summarize.get("mode", "extractive"),
            "model": summarize.get("model", DEFAULT_MODEL),
            "max_cost_usd": float(summarize.get("max_cost_usd", 0.50) or 0.50),
        },
    }


def db_path() -> Path:
    """Resolve the SQLite store path (AI_RADAR_DB overrides the XDG default)."""
    override = os.environ.get("AI_RADAR_DB")
    if override:
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "ai-radar" / "store.db"


def load_feeds(path: Path | None = None) -> dict:
    """Load and lightly normalize feeds.yaml into a dict.

    Returns keys: arxiv_categories (list[str]), rss_feeds (list[{name,url}]),
    youtube_channels (list[str]), hackernews (dict).
    """
    p = path or feeds_path()
    if not p.exists():
        return {"arxiv_categories": [], "rss_feeds": [], "youtube_channels": [], "hackernews": {}}
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    # Flatten the (purely cosmetic) rss grouping into one list of {name, url}.
    rss_raw = raw.get("rss_feeds", []) or []
    flat_rss: list[dict] = []
    if isinstance(rss_raw, dict):
        for group in rss_raw.values():
            for item in group or []:
                if isinstance(item, dict) and item.get("url"):
                    flat_rss.append({"name": item.get("name", item["url"]), "url": item["url"]})
    elif isinstance(rss_raw, list):
        for item in rss_raw:
            if isinstance(item, dict) and item.get("url"):
                flat_rss.append({"name": item.get("name", item["url"]), "url": item["url"]})

    return {
        "arxiv_categories": list(raw.get("arxiv_categories", []) or []),
        "rss_feeds": flat_rss,
        "youtube_channels": list(raw.get("youtube_channels", []) or []),
        "hackernews": dict(raw.get("hackernews", {}) or {}),
    }


# --- Network env -----------------------------------------------------------

def anthropic_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def youtube_api_key() -> str | None:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    return key or None


# --- LLM pricing (USD per 1M tokens) ---------------------------------------
# VERIFY against live pricing at https://www.anthropic.com/pricing before relying on
# these for budgeting. Updated 2026-05; the tool records actual token usage per run so
# drift between this table and reality is always visible.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5":  {"input": 1.0,  "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0},
    "claude-opus-4-8":   {"input": 15.0, "output": 75.0},
}

DEFAULT_MODEL = "claude-haiku-4-5"
