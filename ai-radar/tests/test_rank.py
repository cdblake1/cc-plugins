from __future__ import annotations

import datetime as dt

from ai_radar.rank import dedup, score, top_items


def _doc(source, title, url, date="2026-05-30"):
    return {"source": source, "title": title, "url": url,
            "publish_date": date, "fetched_at": date + "T00:00:00Z"}


def test_dedup_merges_same_url():
    docs = [
        _doc("hackernews", "New model X released", "http://same"),
        _doc("rss", "Totally different headline here", "http://same"),
    ]
    reps = dedup(docs)
    assert len(reps) == 1
    assert reps[0]["corroboration"] == 2


def test_dedup_merges_similar_titles_and_keeps_authoritative():
    docs = [
        _doc("hackernews", "Scaling laws for language models", "http://a"),
        _doc("arxiv", "Scaling laws for language models", "http://b"),
    ]
    reps = dedup(docs)
    assert len(reps) == 1
    # arxiv (higher weight) becomes the representative; corroboration counted
    assert reps[0]["source"] == "arxiv"
    assert reps[0]["corroboration"] == 2


def test_dedup_keeps_distinct_items():
    docs = [
        _doc("rss", "Diffusion models for audio", "http://a"),
        _doc("rss", "Reinforcement learning from human feedback", "http://b"),
    ]
    assert len(dedup(docs)) == 2


def test_score_rewards_recency_source_and_corroboration():
    today = dt.date(2026, 6, 1)
    recent_paper = _doc("arxiv", "x", "http://1", date="2026-05-30")
    old_hn = _doc("hackernews", "y", "http://2", date="2025-06-01")
    assert score(recent_paper, today=today) > score(old_hn, today=today)
    # corroboration boosts score
    corro = dict(recent_paper, corroboration=3)
    assert score(corro, today=today) > score(recent_paper, today=today)


def test_top_items_dedups_and_limits():
    docs = [
        _doc("arxiv", "alpha results", "http://1", date="2026-05-30"),
        _doc("hackernews", "alpha results", "http://1b", date="2026-05-30"),  # dup title
        _doc("rss", "beta findings", "http://2", date="2026-05-29"),
        _doc("github", "gamma tool", "http://3", date="2026-05-28"),
    ]
    top = top_items(docs, 2, today=dt.date(2026, 6, 1))
    assert len(top) == 2
    # the deduped arxiv item (highest weight + corroboration) ranks first
    assert top[0]["source"] == "arxiv"
