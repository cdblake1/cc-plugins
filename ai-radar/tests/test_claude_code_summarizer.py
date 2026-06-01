"""Subscription-backed summarizer (headless `claude` CLI) — subprocess fully mocked."""

from __future__ import annotations

import subprocess
import types

from ai_radar.summarize.claude_code import ClaudeCodeSummarizer


def _patch_cli(monkeypatch, *, present=True, token="tok", run=None):
    monkeypatch.setenv("CLAUDE_CLI_BIN", "claude-test")
    monkeypatch.setattr("ai_radar.summarize.claude_code.shutil.which",
                        lambda name: "/usr/bin/claude-test" if present else None)
    if token is None:
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
    if run is not None:
        monkeypatch.setattr(subprocess, "run", run)


def test_available_requires_cli_and_token(monkeypatch):
    _patch_cli(monkeypatch, present=True, token="tok")
    assert ClaudeCodeSummarizer().available is True

    _patch_cli(monkeypatch, present=False, token="tok")
    assert ClaudeCodeSummarizer().available is False

    _patch_cli(monkeypatch, present=True, token=None)
    assert ClaudeCodeSummarizer().available is False


def test_summarize_document_parses_cli_json(monkeypatch):
    captured = {}

    def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None, env=None):
        captured["cmd"] = cmd
        captured["input"] = input
        # The CLI echoes a structured brief as text on stdout.
        return types.SimpleNamespace(
            returncode=0,
            stdout='{"main_idea":"MI","key_findings":["a","b"],"why_it_matters":"W"}',
            stderr="",
        )

    _patch_cli(monkeypatch, run=fake_run)
    s = ClaudeCodeSummarizer()
    brief = s.summarize_document("some content about agents", "article")
    assert brief["main_idea"] == "MI"
    assert brief["key_findings"] == ["a", "b"]
    # No metered cost on the subscription path.
    assert s.cost_usd == 0.0
    # System prompt goes via -p; the document payload is piped on stdin (argv-safe).
    assert "-p" in captured["cmd"] and "claude-test" in captured["cmd"][0]
    assert "some content about agents" in captured["input"]


def test_synthesize_topic_uses_cli_text(monkeypatch):
    def fake_run(cmd, **kw):
        return types.SimpleNamespace(returncode=0, stdout="A flowing synthesis.", stderr="")

    _patch_cli(monkeypatch, run=fake_run)
    s = ClaudeCodeSummarizer()
    out = s.synthesize_topic("agentic coding", [{"main_idea": "x", "key_findings": ["y"]}])
    assert out == "A flowing synthesis."


def test_call_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kw):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="rate limited")

    _patch_cli(monkeypatch, run=fake_run)
    s = ClaudeCodeSummarizer()
    # digest._topic_synthesis wraps this in try/except → extractive fallback, but the raw
    # call must surface the failure.
    try:
        s.synthesize_topic("t", [{"main_idea": "x"}])
    except RuntimeError as exc:
        assert "exited 1" in str(exc) and "rate limited" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError on non-zero CLI exit")
