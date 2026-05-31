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


def test_migration_adds_summary_columns_to_old_db(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    # v1-era documents table: no summary_* columns.
    conn.executescript(
        """
        CREATE TABLE documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, source TEXT NOT NULL,
          content_type TEXT NOT NULL, external_id TEXT NOT NULL, url TEXT NOT NULL,
          title TEXT, author TEXT, publish_date TEXT, fetched_at TEXT NOT NULL,
          topic TEXT NOT NULL, lang TEXT, content TEXT NOT NULL, meta_json TEXT,
          UNIQUE(source, external_id));
        INSERT INTO documents (source, content_type, external_id, url, title, fetched_at, topic, content)
        VALUES ('rss','article','e1','http://x/1','Old Title','2026-05-31T00:00:00Z','ai','body text');
        """
    )
    conn.commit()
    conn.close()

    s = Store.open(path)  # opening runs the migration
    cols = {r["name"] for r in s.conn.execute("PRAGMA table_info(documents)").fetchall()}
    assert {"summary_json", "summary_model", "summarized_at"} <= cols

    pending = s.unsummarized_documents(model="claude-sonnet-4-6")
    assert len(pending) == 1
    s.save_doc_summary(pending[0]["id"], summary_json='{"main_idea":"x"}',
                       model="claude-sonnet-4-6", at="2026-05-31T00:00:00Z")
    assert s.unsummarized_documents(model="claude-sonnet-4-6") == []
    s.close()


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
