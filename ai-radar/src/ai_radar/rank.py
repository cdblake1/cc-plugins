"""Ranking + de-duplication for the curated digest (pure, deterministic, no deps).

Selects the top items per topic by a transparent score: recency + source weight +
cross-source corroboration (a story surfaced by multiple sources ranks higher). Near-
identical items (same URL or near-identical titles) are merged first so the digest isn't
repetitive.

Improvement vector (not built here): an LLM could re-rank by importance.
"""

from __future__ import annotations

import datetime as dt

from .textutil import tokens

# Higher = more authoritative/primary. Tunable.
SOURCE_WEIGHT = {
    "arxiv": 1.0,
    "semanticscholar": 0.95,
    "paperswithcode": 0.9,
    "rss": 0.7,
    "github": 0.6,
    "youtube": 0.55,
    "hackernews": 0.5,
}

_W_RECENCY = 1.0
_W_CORROBORATION = 0.5
_RECENCY_HALFLIFE_DAYS = 180


def _title_sig(title: str) -> frozenset:
    return frozenset(tokens(title or ""))


def _similar(a: frozenset, b: frozenset, threshold: float = 0.6) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    union = len(a | b)
    return union > 0 and inter / union >= threshold


def dedup(docs: list[dict]) -> list[dict]:
    """Merge near-identical docs. Each kept rep gains a 'corroboration' count.

    A duplicate = same URL, or title-token Jaccard >= 0.6. The higher source-weight rep is kept.
    """
    reps: list[dict] = []
    sigs: list[frozenset] = []
    urls: dict[str, int] = {}
    for d in docs:
        url = (d.get("url") or "").strip()
        sig = _title_sig(d.get("title", ""))
        idx = urls.get(url) if url else None
        if idx is None:
            for i, s in enumerate(sigs):
                if _similar(sig, s):
                    idx = i
                    break
        if idx is None:
            rep = dict(d)
            rep["corroboration"] = 1
            reps.append(rep)
            sigs.append(sig)
            if url:
                urls[url] = len(reps) - 1
        else:
            rep = reps[idx]
            rep["corroboration"] = rep.get("corroboration", 1) + 1
            # Keep the more authoritative source as the representative.
            if SOURCE_WEIGHT.get(d.get("source", ""), 0) > SOURCE_WEIGHT.get(rep.get("source", ""), 0):
                corr = rep["corroboration"]
                reps[idx] = dict(d)
                reps[idx]["corroboration"] = corr
                sigs[idx] = sig
    return reps


def score(doc: dict, *, today: dt.date | None = None) -> float:
    today = today or dt.date.today()
    sw = SOURCE_WEIGHT.get(doc.get("source", ""), 0.4)
    # recency
    rec = 0.0
    date = doc.get("publish_date") or (doc.get("fetched_at") or "")[:10]
    try:
        d = dt.date.fromisoformat(date[:10])
        days = max(0, (today - d).days)
        rec = max(0.0, 1.0 - days / _RECENCY_HALFLIFE_DAYS)
    except (ValueError, TypeError):
        rec = 0.0
    corr = doc.get("corroboration", 1) - 1
    return sw + _W_RECENCY * rec + _W_CORROBORATION * corr


def top_items(docs: list[dict], n: int, *, today: dt.date | None = None) -> list[dict]:
    """De-duplicate, score, and return the top n items (highest score first)."""
    merged = dedup(docs)
    merged.sort(key=lambda d: score(d, today=today), reverse=True)
    return merged[:n]
