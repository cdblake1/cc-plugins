from __future__ import annotations

from ai_radar.digest import build_digest_markdown, run_digest


def _cfg(mode="extractive"):
    return {
        "topics": ["agentic coding", "llm eval"],
        "since_days": 30,
        "max_per_source": 5,
        "sources": "fake",
        "summarize": {"mode": mode, "model": "claude-haiku-4-5", "max_cost_usd": 0.50},
    }


def test_run_digest_writes_markdown(tmp_path, store, fake_source_factory):
    src = fake_source_factory()
    # sources="fake" → resolve_sources rejects unknown; inject via a topics cfg whose
    # source list is bypassed by get_source returning the fake for any name.
    cfg = _cfg()
    cfg["sources"] = "arxiv"  # any known name; get_source override ignores it
    result = run_digest(
        store, cfg, out_dir=tmp_path, date="2026-05-31", get_source=lambda n: src
    )
    assert result["date"] == "2026-05-31"
    assert (tmp_path / "2026-05-31.md").exists()
    assert (tmp_path / "latest.md").exists()
    text = (tmp_path / "2026-05-31.md").read_text()
    assert "# AI Radar Digest — 2026-05-31" in text
    assert "agentic coding" in text and "llm eval" in text
    assert "### Sources" in text
    # both topics summarized + persisted
    assert store.latest_summary("agentic coding") is not None


def test_run_digest_claude_falls_back_without_key(tmp_path, store, fake_source_factory, monkeypatch):
    import ai_radar.digest as digest_mod

    monkeypatch.setattr(digest_mod.config, "anthropic_api_key", lambda: None)
    src = fake_source_factory()
    cfg = _cfg(mode="claude")
    cfg["sources"] = "arxiv"
    result = run_digest(store, cfg, out_dir=tmp_path, date="2026-05-31", get_source=lambda n: src)
    # Fell back to extractive → zero cost, summary still produced.
    assert result["total_cost"] == 0.0
    assert store.latest_summary("agentic coding")["mode"] == "extractive"


def test_build_digest_markdown_has_toc_and_anchors():
    results = [
        {"topic": "Agentic Coding", "docs": [
            {"title": "T1", "url": "http://x/1", "source": "rss", "author": "A",
             "publish_date": "2026-05-30", "fetched_at": "2026-05-31T00:00:00Z"}],
         "summary": "- point", "mode": "extractive", "model": None, "cost": 0.0},
    ]
    md = build_digest_markdown("2026-05-31", "2026-05-01", ["rss"], results, 0.0)
    assert "## Topics" in md
    assert "[Agentic Coding](#agentic-coding)" in md
    assert "[T1](http://x/1)" in md
