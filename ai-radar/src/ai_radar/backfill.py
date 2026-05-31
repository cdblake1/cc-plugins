"""Windowed historical backfill.

Pulling one giant `since=N months ago` request doesn't work — every source caps results
and returns the most-recent matches. Instead we iterate fixed date windows oldest→newest,
each with its own [since, until), so coverage is even and caps are respected. The
UNIQUE(source, external_id) constraint makes overlapping/re-runs harmless (resumable).

Per-source reality: arXiv and Hacker News have full date-ranged history; YouTube backfills
well per --channel; RSS feeds only serve recent entries (no historical archive), so they
contribute little to a backfill — that's expected, not a bug.
"""

from __future__ import annotations

import datetime as dt
import time

from .models import FetchParams
from .sources import registry
from .storage import Store

_WINDOW_DAYS = {"weekly": 7, "monthly": 30}


def date_windows(months: int, window: str, *, today: dt.date | None = None) -> list[tuple[str, str]]:
    """Return [(since, until), ...] oldest→newest covering the last `months` months."""
    today = today or dt.date.today()
    start = today - dt.timedelta(days=months * 30)
    step = _WINDOW_DAYS.get(window, 7)
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor < today:
        nxt = min(cursor + dt.timedelta(days=step), today)
        windows.append((cursor.isoformat(), nxt.isoformat()))
        cursor = nxt
    return windows


def backfill(
    store: Store,
    topic: str,
    *,
    months: int = 3,
    window: str = "weekly",
    sources: str = "all",
    channel: str | None = None,
    max_per_window: int = 20,
    pause_seconds: float = 1.0,
    today: dt.date | None = None,
    get_source=registry.get_source,
    log=lambda *a: None,
) -> dict:
    """Backfill a topic across sequential date windows. Returns totals."""
    from .cli import fetch_documents  # lazy: avoid import cycle

    source_names = registry.resolve_sources(sources)
    windows = date_windows(months, window, today=today)
    totals = {"windows": len(windows), "inserted": 0, "duplicate": 0, "skipped": 0}
    log(f"backfill '{topic}': {len(windows)} {window} window(s) over ~{months} month(s) "
        f"from {source_names}")

    for i, (since, until) in enumerate(windows):
        params = FetchParams(
            topic=topic, since=since, until=until, max_results=max_per_window, channel=channel
        )
        stats = fetch_documents(store, params, source_names, get_source=get_source, log=log)
        totals["inserted"] += stats["inserted"]
        totals["duplicate"] += stats["duplicate"]
        totals["skipped"] += stats["skipped"]
        log(f"  [{since}..{until}) → +{stats['inserted']} new")
        # Be polite to the public APIs between windows (skipped on the final window).
        if pause_seconds and i < len(windows) - 1:
            time.sleep(pause_seconds)
    return totals
