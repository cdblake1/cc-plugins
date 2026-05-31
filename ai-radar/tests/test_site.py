from __future__ import annotations

import json
import re

from ai_radar.models import Document
from ai_radar.site import build_site
from ai_radar.storage import Store


def _doc(store, ext, topic, title, content):
    store.upsert_document(Document(
        source="rss", content_type="article", external_id=ext, url=f"http://x/{ext}",
        topic=topic, content=content, fetched_at="2026-05-31T00:00:00Z", title=title,
        publish_date="2026-05-30", author="Auth",
    ))


def test_build_site_is_self_contained(tmp_path, store: Store):
    _doc(store, "1", "agentic coding", "Agentic coding", "Autonomous agents write and run code.")
    _doc(store, "2", "tool use", "Tool use", "Agents call tools to write code autonomously.")
    store.save_summary(topic="agentic coding", mode="extractive", model=None,
                       document_ids=[1], summary="- agents write code",
                       token_usage=None, created_at="2026-05-31T00:00:00Z")

    result = build_site(store, tmp_path, title="My Radar")
    index = tmp_path / "index.html"
    assert index.exists()
    assert (tmp_path / ".nojekyll").exists()

    htmltext = index.read_text()
    # data embedded inline (no external fetch needed) and no external script/style/CDN refs
    assert "<title>My Radar</title>" in htmltext
    assert "<script src=" not in htmltext   # no external/CDN JS
    assert "<link " not in htmltext          # no external stylesheet

    # extract the embedded JSON and verify structure
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', htmltext, re.S)
    data = json.loads(m.group(1))
    names = {t["name"] for t in data["topics"]}
    assert {"agentic coding", "tool use"} <= names
    ac = next(t for t in data["topics"] if t["name"] == "agentic coding")
    assert ac["summary"] == "- agents write code"
    assert ac["docs"][0]["url"] == "http://x/1"
    assert result["documents"] == 2
