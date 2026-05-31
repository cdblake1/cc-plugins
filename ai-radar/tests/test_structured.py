from __future__ import annotations

import sys
import types

import pytest

from ai_radar.summarize.structured import DocumentSummarizer, _parse_brief


def _install_fake_anthropic(monkeypatch, *, text=None):
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            system = kwargs["system"][0]["text"]
            out = text
            if out is None:
                out = ('{"main_idea":"It scales agents","key_findings":["+12% on bench","uses tools"],'
                       '"why_it_matters":"cheaper agents"}') if "JSON object" in system else "Synthesis."
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text=out)],
                usage=types.SimpleNamespace(input_tokens=1000, output_tokens=200),
            )

    class FakeAnthropic:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = FakeMessages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return captured


def test_summarize_document_returns_structured_brief(monkeypatch):
    cap = _install_fake_anthropic(monkeypatch)
    s = DocumentSummarizer("claude-sonnet-4-6", api_key="k")
    brief = s.summarize_document("A paper about scaling agents.", "paper")
    assert brief["main_idea"] == "It scales agents"
    assert brief["key_findings"] == ["+12% on bench", "uses tools"]
    assert brief["why_it_matters"] == "cheaper agents"
    # cost tracked from usage (Sonnet: 3/MTok in, 15/MTok out)
    assert s.cost_usd == pytest.approx(1000 / 1e6 * 3 + 200 / 1e6 * 15, abs=1e-9)
    # prompt caching applied to the system block
    assert cap["kwargs"]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_synthesize_topic_and_overview(monkeypatch):
    _install_fake_anthropic(monkeypatch)
    s = DocumentSummarizer("claude-sonnet-4-6", api_key="k")
    syn = s.synthesize_topic("agents", [{"main_idea": "x", "key_findings": ["y"]}])
    assert syn == "Synthesis."
    ov = s.synthesize_overview({"agents": "the agents synthesis"})
    assert ov == "Synthesis."
    # empty inputs short-circuit (no call, empty string)
    assert s.synthesize_topic("t", []) == ""
    assert s.synthesize_overview({}) == ""


def test_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = DocumentSummarizer("claude-sonnet-4-6")
    assert s.available is False
    with pytest.raises(RuntimeError):
        s.summarize_document("text", "article")


def test_document_content_is_capped(monkeypatch):
    cap = _install_fake_anthropic(monkeypatch)
    s = DocumentSummarizer("claude-sonnet-4-6", api_key="k", max_doc_tokens=10)
    huge = "word " * 100000
    s.summarize_document(huge, "paper")
    user_msg = cap["kwargs"]["messages"][0]["content"]
    assert len(user_msg) < 1000  # truncated to ~max_doc_tokens*3.5 chars


def test_parse_brief_tolerant():
    # chatty / fenced output around JSON
    b = _parse_brief('Sure!\n```json\n{"main_idea":"M","key_findings":"single"}\n```')
    assert b["main_idea"] == "M"
    assert b["key_findings"] == ["single"]  # string coerced to list
    # total garbage → main_idea fallback, empty findings
    b2 = _parse_brief("not json at all")
    assert b2["main_idea"] == "not json at all" and b2["key_findings"] == []
