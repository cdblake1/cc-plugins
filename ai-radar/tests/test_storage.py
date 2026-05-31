from __future__ import annotations

from ai_radar.models import Document, Run
from ai_radar.storage import Store


def _doc(external_id="v1", source="youtube", content="text", run_id=None):
    return Document(
        source=source,
        content_type="transcript",
        external_id=external_id,
        url=f"http://x/{external_id}",
        topic="ai",
        content=content,
        fetched_at="2026-05-31T00:00:00Z",
        title=f"title {external_id}",
        publish_date="2026-05-30",
        run_id=run_id,
    )


def test_schema_initializes(store: Store):
    tables = {
        r["name"]
        for r in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"runs", "documents", "summaries"} <= tables


def test_run_lifecycle_and_linkage(store: Store):
    run_id = store.start_run(Run(topic="ai", sources="youtube", params_json="{}", started_at="t0"))
    assert store.upsert_document(_doc("v1", run_id=run_id)) is True
    store.finish_run(run_id, finished_at="t1", item_count=1, status="ok")

    rows = store.query_documents(run_id=run_id)
    assert len(rows) == 1 and rows[0]["topic"] == "ai"
    run_row = store.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    assert run_row["status"] == "ok" and run_row["item_count"] == 1


def test_upsert_is_idempotent(store: Store):
    assert store.upsert_document(_doc("dup")) is True
    # Same (source, external_id) → ignored, returns False, no duplicate row.
    assert store.upsert_document(_doc("dup", content="changed")) is False
    rows = store.query_documents(topic="ai")
    assert len(rows) == 1


def test_query_filters(store: Store):
    store.upsert_document(_doc("v1", source="youtube"))
    store.upsert_document(_doc("a1", source="arxiv"))
    assert len(store.query_documents(source="youtube")) == 1
    assert len(store.query_documents(source="arxiv")) == 1
    assert len(store.query_documents(topic="ai")) == 2
    assert len(store.query_documents(topic="ai", limit=1)) == 1


def test_summary_roundtrip(store: Store):
    sid = store.save_summary(
        topic="ai", mode="extractive", model=None, document_ids=[1, 2],
        summary="the summary", token_usage={"input": 10, "output": 0},
        created_at="2026-05-31T00:00:00Z",
    )
    assert sid > 0
    latest = store.latest_summary("ai")
    assert latest["summary"] == "the summary" and latest["mode"] == "extractive"
    assert store.latest_summary("nope") is None
