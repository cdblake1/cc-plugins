"""Generate a cross-linked markdown wiki from the stored documents.

One page per topic (summary + source references + cross-links to related topics and
related reading from other topics) plus an index. Cross-references are computed for free
from the FTS index / shared salient terms — no embeddings, no API calls.
"""

from __future__ import annotations

from pathlib import Path

from .storage import Store
from .textutil import top_terms


def slug(topic: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in topic.lower()).strip("-") or "topic"


def _topic_terms(store: Store, topic: str, docs: list[dict]) -> set[str]:
    blob = " ".join(f"{d.get('title') or ''} {d['content']}" for d in docs)
    return set(top_terms(blob, n=20))


def related_topics(term_map: dict[str, set[str]], topic: str, *, limit: int = 5) -> list[tuple[str, int]]:
    """Rank other topics by shared salient terms (cheap, deterministic)."""
    mine = term_map.get(topic, set())
    scored = []
    for other, terms in term_map.items():
        if other == topic:
            continue
        overlap = len(mine & terms)
        if overlap:
            scored.append((other, overlap))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:limit]


def build_wiki(store: Store, out_dir: str | Path, *, topics: list[str] | None = None) -> dict:
    """Write the wiki to out_dir. Returns {"index", "pages": [paths]}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    topic_list = topics or store.distinct_topics()

    # Precompute per-topic docs + salient terms for cross-referencing.
    docs_by_topic: dict[str, list[dict]] = {}
    term_map: dict[str, set[str]] = {}
    for topic in topic_list:
        docs = store.query_documents(topic=topic)
        docs_by_topic[topic] = docs
        term_map[topic] = _topic_terms(store, topic, docs)

    pages: list[str] = []
    for topic in topic_list:
        page = out / f"{slug(topic)}.md"
        page.write_text(
            _render_topic_page(store, topic, docs_by_topic[topic], term_map), encoding="utf-8"
        )
        pages.append(str(page))

    index = out / "index.md"
    index.write_text(_render_index(topic_list, docs_by_topic), encoding="utf-8")
    return {"index": str(index), "pages": pages}


def _render_index(topic_list: list[str], docs_by_topic: dict[str, list[dict]]) -> str:
    lines = ["# AI Radar Wiki", "", f"{len(topic_list)} topic(s) tracked.", "", "## Topics", ""]
    for topic in sorted(topic_list, key=lambda t: len(docs_by_topic[t]), reverse=True):
        n = len(docs_by_topic[topic])
        lines.append(f"- [{topic}]({slug(topic)}.md) — {n} source(s)")
    lines.append("")
    return "\n".join(lines)


def _render_topic_page(store: Store, topic: str, docs: list[dict], term_map: dict[str, set[str]]) -> str:
    lines = [f"# {topic}", "", "[← index](index.md)", ""]

    summary = store.latest_summary(topic)
    if summary and summary.get("summary"):
        lines += [f"## Summary ({summary['mode']})", "", summary["summary"], ""]

    # Cross-references to related topics (shared salient terms).
    rel = related_topics(term_map, topic)
    if rel:
        lines += ["## Related topics", ""]
        for other, overlap in rel:
            lines.append(f"- [{other}]({slug(other)}.md) — {overlap} shared term(s)")
        lines.append("")

    # Source references.
    lines += [f"## Sources ({len(docs)})", ""]
    for d in docs:
        d_date = d.get("publish_date") or (d.get("fetched_at") or "")[:10]
        title = d.get("title") or d["url"]
        author = d.get("author") or "unknown"
        lines.append(f"- [{title}]({d['url']}) — {d['source']} · {author} · {d_date}")
    lines.append("")

    # Cross-topic "related reading": documents from OTHER topics that match this topic.
    cross = store.search(topic, limit=8)
    cross = [c for c in cross if c["topic"] != topic][:5]
    if cross:
        lines += ["## Related reading (other topics)", ""]
        for c in cross:
            title = c.get("title") or c["url"]
            lines.append(f"- [{title}]({c['url']}) — *{c['topic']}* · {c['source']}")
        lines.append("")
    return "\n".join(lines)
