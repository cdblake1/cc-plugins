from __future__ import annotations

import sys
import types

import pytest

from ai_radar.summarize import get_summarizer
from ai_radar.summarize.claude import ClaudeSummarizer

DOCS = [
    "Agentic coding lets models edit files and run tools. Agentic coding is improving fast.",
    "New model updates improve reasoning. Reasoning benchmarks rose this month.",
]


def test_extractive_is_free_and_deterministic():
    s = get_summarizer("extractive")
    est = s.estimate(DOCS)
    assert est.estimated_cost_usd == 0.0 and est.token_usage["output"] == 0

    r1 = s.summarize(DOCS)
    r2 = s.summarize(DOCS)
    assert r1.summary == r2.summary  # deterministic
    assert r1.summary.startswith("- ") and r1.estimated_cost_usd == 0.0


def test_emit_bundles_documents():
    s = get_summarizer("emit")
    r = s.summarize(DOCS)
    assert "Document 1" in r.summary and "Document 2" in r.summary
    assert r.estimated_cost_usd == 0.0


def test_claude_estimate_makes_no_call_and_costs_more_than_zero():
    # No anthropic module injected: if estimate() tried to call the API this would error.
    s = ClaudeSummarizer(model="claude-haiku-4-5")
    est = s.estimate(DOCS)
    assert est.estimated_cost_usd is not None and est.estimated_cost_usd > 0
    assert est.model == "claude-haiku-4-5"
    assert "ESTIMATE ONLY" in est.meta["note"]


def test_claude_summarize_records_usage(monkeypatch):
    # Fake the anthropic SDK so no network/key is needed.
    created = {}

    class FakeMessages:
        def create(self, **kwargs):
            created.update(kwargs)
            block = types.SimpleNamespace(text="A tidy summary.")
            usage = types.SimpleNamespace(input_tokens=1000, output_tokens=200)
            return types.SimpleNamespace(content=[block], usage=usage)

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = FakeMessages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)

    s = ClaudeSummarizer(model="claude-haiku-4-5", api_key="test-key")
    r = s.summarize(DOCS)
    assert r.summary == "A tidy summary."
    assert r.token_usage == {"input": 1000, "output": 200}
    # 1000/1e6*1.0 + 200/1e6*5.0 = 0.001 + 0.001 = 0.002
    assert r.estimated_cost_usd == pytest.approx(0.002, abs=1e-6)
    # Prompt caching applied to the system block.
    assert created["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_claude_summarize_without_key_raises():
    s = ClaudeSummarizer(model="claude-haiku-4-5", api_key=None)
    # Ensure env has no key for this test.
    import os

    os.environ.pop("ANTHROPIC_API_KEY", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        s.summarize(DOCS)
