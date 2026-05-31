from __future__ import annotations

import datetime as dt

from ai_radar.backfill import date_windows
from ai_radar.models import Document
from ai_radar.storage import Store
from ai_radar.textutil import fts_match_query, top_terms
from ai_radar.wiki import build_wiki, related_topics, slug


def _doc(store, ext, topic, title, content, source="rss"):
    store.upsert_document(Document(
        source=source, content_type="article", external_id=ext, url=f"http://x/{ext}",
        topic=topic, content=content, fetched_at="2026-05-31T00:00:00Z", title=title,
        publish_date="2026-05-30",
    ))


# --- text utils ------------------------------------------------------------

def test_top_terms_and_fts_query():
    terms = top_terms("agentic coding agents agentic tools coding", n=3)
    assert "agentic" in terms and "coding" in terms
    q = fts_match_query("agentic coding!!! <tools>")
    assert '"agentic"' in q and " OR " in q
    assert fts_match_query("the a an") == ""  # all stopwords → nothing searchable


# --- FTS search ------------------------------------------------------------

def test_search_ranks_and_filters(store: Store):
    _doc(store, "1", "agents", "Agentic coding", "Agentic coding with autonomous tool use.")
    _doc(store, "2", "rag", "Retrieval", "Retrieval augmented generation for grounding.")
    _doc(store, "3", "agents", "Tool use", "Models call tools and APIs autonomously.")

    hits = store.search("agentic tool use")
    assert hits and hits[0]["external_id"] in {"1", "3"}
    assert all("score" in h for h in hits)

    scoped = store.search("tool", topic="agents")
    assert scoped and all(h["topic"] == "agents" for h in scoped)
    assert store.search("zzznotpresent") == []


def test_related_cross_topic(store: Store):
    _doc(store, "1", "agents", "Agentic coding", "Autonomous agents use tools to write code.")
    _doc(store, "2", "tools", "Tool use", "Agents use tools and APIs to write code autonomously.")
    rel = store.related(1, cross_topic_only=True)
    assert rel and rel[0]["topic"] == "tools"


def test_fts_backfills_preexisting_rows(tmp_path):
    # Insert via a connection, then reopen: _sync_fts should index the prior row.
    path = tmp_path / "s.db"
    s = Store.open(path)
    _doc(s, "1", "agents", "Agentic coding", "Autonomous agents use tools.")
    s.close()
    s2 = Store.open(path)
    assert s2.search("autonomous agents")  # found after reopen
    s2.close()


# --- backfill windows ------------------------------------------------------

def test_date_windows_cover_range_in_sequence():
    today = dt.date(2026, 5, 31)
    wins = date_windows(months=1, window="weekly", today=today)
    assert wins[0][0] < wins[-1][1]            # oldest → newest
    assert wins[-1][1] == today.isoformat()    # ends today
    # contiguous: each window's until is the next window's since
    for (s1, u1), (s2, u2) in zip(wins, wins[1:]):
        assert u1 == s2


# --- wiki ------------------------------------------------------------------

def test_related_topics_by_shared_terms():
    term_map = {
        "a": {"agent", "tool", "code"},
        "b": {"agent", "tool", "rag"},
        "c": {"vision", "image"},
    }
    rel = related_topics(term_map, "a")
    assert rel[0][0] == "b" and rel[0][1] == 2
    assert "c" not in [r[0] for r in rel]


def test_build_wiki_writes_pages_and_index(tmp_path, store: Store):
    _doc(store, "1", "agentic coding", "Agentic coding", "Autonomous agents write and run code.")
    _doc(store, "2", "tool use", "Tool use", "Agents call tools and run code autonomously.")
    store.save_summary(topic="agentic coding", mode="extractive", model=None,
                       document_ids=[1], summary="- agents write code",
                       token_usage=None, created_at="2026-05-31T00:00:00Z")

    result = build_wiki(store, tmp_path)
    assert (tmp_path / "index.md").exists()
    assert len(result["pages"]) == 2

    page = (tmp_path / f"{slug('agentic coding')}.md").read_text()
    assert "# agentic coding" in page
    assert "## Summary" in page and "agents write code" in page
    assert "## Sources" in page and "http://x/1" in page
    # cross-links: related topics and/or related reading reference the other topic
    assert "tool use" in page
    index = (tmp_path / "index.md").read_text()
    assert "[agentic coding](agentic-coding.md)" in index
