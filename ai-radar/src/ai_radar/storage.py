"""SQLite persistence: schema + a small DAO.

Uses only stdlib sqlite3. The store is idempotent on (source, external_id) so re-fetching
the same topic never duplicates rows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Document, Run

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  params_json TEXT NOT NULL,
  sources TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  item_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER REFERENCES runs(id),
  source TEXT NOT NULL,
  content_type TEXT NOT NULL,
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  author TEXT,
  publish_date TEXT,
  fetched_at TEXT NOT NULL,
  topic TEXT NOT NULL,
  lang TEXT,
  content TEXT NOT NULL,
  meta_json TEXT,
  UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  mode TEXT NOT NULL,
  model TEXT,
  document_ids TEXT NOT NULL,
  summary TEXT NOT NULL,
  token_usage TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_topic ON documents(topic);
CREATE INDEX IF NOT EXISTS idx_documents_run   ON documents(run_id);
"""


class Store:
    """Thin DAO over a SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @classmethod
    def open(cls, path: str | Path) -> "Store":
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        return cls(conn)

    def close(self) -> None:
        self.conn.close()

    # --- runs --------------------------------------------------------------

    def start_run(self, run: Run) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (topic, params_json, sources, started_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (run.topic, run.params_json, run.sources, run.started_at, run.status),
        )
        self.conn.commit()
        run.id = int(cur.lastrowid)
        return run.id

    def finish_run(self, run_id: int, *, finished_at: str, item_count: int, status: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, item_count = ?, status = ? WHERE id = ?",
            (finished_at, item_count, status, run_id),
        )
        self.conn.commit()

    # --- documents ---------------------------------------------------------

    def upsert_document(self, doc: Document) -> bool:
        """Insert a document; ignore if (source, external_id) already exists.

        Returns True if a new row was inserted, False if it was a duplicate.
        """
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO documents "
            "(run_id, source, content_type, external_id, url, title, author, "
            " publish_date, fetched_at, topic, lang, content, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc.run_id, doc.source, doc.content_type, doc.external_id, doc.url,
                doc.title, doc.author, doc.publish_date, doc.fetched_at, doc.topic,
                doc.lang, doc.content, json.dumps(doc.meta or {}),
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def query_documents(
        self,
        *,
        topic: str | None = None,
        source: str | None = None,
        run_id: int | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM documents"
        clauses: list[str] = []
        args: list[object] = []
        if topic is not None:
            clauses.append("topic = ?")
            args.append(topic)
        if source is not None:
            clauses.append("source = ?")
            args.append(source)
        if run_id is not None:
            clauses.append("run_id = ?")
            args.append(run_id)
        if since is not None:
            # Scope to a window using publish_date when known, else fetched_at.
            clauses.append("COALESCE(publish_date, fetched_at) >= ?")
            args.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(publish_date, fetched_at) DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # --- summaries ---------------------------------------------------------

    def save_summary(
        self,
        *,
        topic: str,
        mode: str,
        model: str | None,
        document_ids: list[int],
        summary: str,
        token_usage: dict | None,
        created_at: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO summaries (topic, mode, model, document_ids, summary, token_usage, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                topic, mode, model, json.dumps(document_ids), summary,
                json.dumps(token_usage) if token_usage else None, created_at,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def latest_summary(self, topic: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM summaries WHERE topic = ? ORDER BY id DESC LIMIT 1", (topic,)
        ).fetchone()
        return dict(row) if row else None
