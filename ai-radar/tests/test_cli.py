from __future__ import annotations

import io

from ai_radar.cli import fetch_documents, run_summarize
from ai_radar.models import FetchParams


def test_fetch_documents_inserts_and_dedupes(store, fake_source_factory):
    src = fake_source_factory()
    get = lambda name: src  # noqa: E731 — inject the fake regardless of name
    params = FetchParams(topic="ai", max_results=10)

    stats = fetch_documents(store, params, ["fake"], get_source=get)
    assert stats["inserted"] == 2 and stats["skipped"] == 0

    # Re-running the same fetch upserts nothing new.
    stats2 = fetch_documents(store, params, ["fake"], get_source=get)
    assert stats2["inserted"] == 0 and stats2["duplicate"] == 2
    assert len(store.query_documents(topic="ai")) == 2


def test_fetch_documents_skips_unavailable(store, fake_source_factory):
    src = fake_source_factory(unavailable=True)
    stats = fetch_documents(store, FetchParams(topic="ai"), ["fake"], get_source=lambda n: src)
    assert stats["inserted"] == 0 and stats["skipped"] == 2


def test_fetch_documents_survives_broken_source(store):
    def boom(name):
        raise ValueError("no such source")

    stats = fetch_documents(store, FetchParams(topic="ai"), ["nope"], get_source=boom)
    assert stats["inserted"] == 0  # did not raise


def _seed(store, fake_source_factory):
    src = fake_source_factory()
    fetch_documents(store, FetchParams(topic="ai"), ["fake"], get_source=lambda n: src)


def test_run_summarize_extractive_saves_summary(store, fake_source_factory):
    _seed(store, fake_source_factory)
    out = io.StringIO()
    res = run_summarize(store, "ai", "extractive", out=out)
    assert res["status"] == "ok"
    assert store.latest_summary("ai")["mode"] == "extractive"


def test_run_summarize_no_documents(store):
    out = io.StringIO()
    res = run_summarize(store, "missing", "extractive", out=out)
    assert res["status"] == "no-documents"


def test_claude_estimate_only_never_calls_api(store, fake_source_factory):
    """Regression guard: estimate-only must not invoke the paid path."""
    _seed(store, fake_source_factory)
    out = io.StringIO()
    # No anthropic installed + no key: if summarize() were reached it would raise.
    res = run_summarize(store, "ai", "claude", estimate_only=True, out=out)
    assert res["status"] == "estimate-only"
    assert "Estimate" in out.getvalue()
    assert store.latest_summary("ai") is None  # nothing persisted


def test_claude_aborts_when_not_confirmed(store, fake_source_factory):
    _seed(store, fake_source_factory)
    out = io.StringIO()
    res = run_summarize(store, "ai", "claude", confirm=lambda prompt: False, out=out)
    assert res["status"] == "aborted"
    assert store.latest_summary("ai") is None
