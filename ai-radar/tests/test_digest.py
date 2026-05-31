from __future__ import annotations

import sys
import types

from ai_radar.digest import build_digest_markdown, run_digest
from ai_radar.summarize.structured import DocumentSummarizer


def _cfg(mode="extractive", model="claude-sonnet-4-6"):
    return {
        "topics": ["agentic coding", "llm eval"],
        "since_days": 3650,
        "max_per_source": 5,
        "sources": "arxiv",  # any known name; get_source override ignores it
        "summarize": {"mode": mode, "model": model, "max_cost_usd": 5.00},
    }


def _fake_anthropic(monkeypatch, *, doc_json='{"main_idea":"MI","key_findings":["a","b"],"why_it_matters":"W"}'):
    """Install a fake anthropic module returning structured JSON for doc calls."""
    class FakeMessages:
        def create(self, **kwargs):
            system = kwargs["system"][0]["text"]
            text = doc_json if "JSON object" in system else "A topic synthesis."
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text=text)],
                usage=types.SimpleNamespace(input_tokens=100, output_tokens=50),
            )

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)


def test_run_digest_extractive_fallback(tmp_path, store, fake_source_factory):
    """No summarizer (no key) → extractive synthesis, snippets, files written."""
    src = fake_source_factory()
    cfg = _cfg(mode="extractive")
    result = run_digest(store, cfg, out_dir=tmp_path, date="2026-05-31",
                        get_source=lambda n: src)
    assert result["date"] == "2026-05-31"
    assert result["cost_usd"] == 0.0
    assert (tmp_path / "2026-05-31.md").exists()
    assert (tmp_path / "latest.md").exists()
    text = (tmp_path / "2026-05-31.md").read_text()
    assert "# AI Radar Digest — 2026-05-31" in text
    assert "agentic coding" in text and "llm eval" in text
    # extractive synthesis persisted so the wiki can show it
    assert store.latest_summary("agentic coding")["mode"] == "extractive"


def test_run_digest_map_reduce_with_llm(tmp_path, store, fake_source_factory, monkeypatch):
    """With a summarizer: per-doc briefs are cached, executive summary + findings rendered."""
    _fake_anthropic(monkeypatch)
    summarizer = DocumentSummarizer("claude-sonnet-4-6", api_key="k")
    cfg = _cfg(mode="claude")
    src = fake_source_factory()
    res = run_digest(store, cfg, out_dir=tmp_path, date="2026-05-31",
                     get_source=lambda n: src, summarizer=summarizer)

    docs = store.query_documents(topic="agentic coding")
    assert docs and all(d["summary_json"] for d in docs)  # every doc summarized + cached
    assert res["cost_usd"] > 0

    md = (tmp_path / "2026-05-31.md").read_text()
    assert "## Executive summary" in md
    assert "**Main idea:** MI" in md and "**Key findings:**" in md

    # Caching: a fresh summarizer re-run summarizes nothing new (no pending docs remain).
    s2 = DocumentSummarizer("claude-sonnet-4-6", api_key="k")
    run_digest(store, cfg, out_dir=tmp_path, date="2026-05-31",
               get_source=lambda n: src, summarizer=s2)
    assert store.unsummarized_documents(model="claude-sonnet-4-6", topic="agentic coding") == []


def test_run_digest_budget_ceiling_defers(tmp_path, store, fake_source_factory, monkeypatch):
    """A tiny budget stops summarization; some docs remain unsummarized for next run."""
    _fake_anthropic(monkeypatch)
    summarizer = DocumentSummarizer("claude-sonnet-4-6", api_key="k")
    cfg = _cfg(mode="claude")
    cfg["summarize"]["max_cost_usd"] = 0.0  # ceiling already met → defer everything
    src = fake_source_factory()
    run_digest(store, cfg, out_dir=tmp_path, date="2026-05-31",
               get_source=lambda n: src, summarizer=summarizer)
    pending = store.unsummarized_documents(model="claude-sonnet-4-6")
    assert len(pending) > 0  # nothing summarized due to budget


def test_build_digest_markdown_has_toc_executive_and_items():
    topic_results = [
        {
            "topic": "Agentic Coding",
            "synthesis": "Lots happening in agents.",
            "total": 3,
            "curated": [
                {"title": "T1", "url": "http://x/1", "source": "rss", "author": "A",
                 "publish_date": "2026-05-30", "fetched_at": "2026-05-31T00:00:00Z",
                 "_brief": {"main_idea": "MI", "key_findings": ["k1"], "why_it_matters": "w"},
                 "_related": [{"title": "R1", "url": "http://r/1"}]},
            ],
        },
    ]
    md = build_digest_markdown("2026-05-31", "2026-05-01", ["rss"], "Top dev bullets.", topic_results)
    assert "## Executive summary" in md and "Top dev bullets." in md
    assert "## Topics" in md and "[Agentic Coding](#agentic-coding)" in md
    assert "[T1](http://x/1)" in md and "**Main idea:** MI" in md
    assert "**Related:**" in md and "+2 more" in md
