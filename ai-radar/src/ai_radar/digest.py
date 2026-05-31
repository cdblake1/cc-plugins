"""Scheduled digest: fetch a set of topics, summarize each, and write one markdown file.

Designed to run unattended (cron / Fly machine), so the Claude path here never prompts —
it instead respects a per-topic cost ceiling and falls back to the free extractive
summarizer when there's no API key or the estimate exceeds the ceiling.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import config
from .models import FetchParams
from .sources import registry
from .storage import Store
from .summarize import get_summarizer


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _summarize_topic(store: Store, topic: str, docs: list[dict], scfg: dict, log) -> dict:
    """Summarize one topic's documents, with automatic fallback to extractive.

    Returns {"summary", "mode", "model", "cost"}.
    """
    contents = [d["content"] for d in docs]
    doc_ids = [d["id"] for d in docs]
    mode = scfg["mode"]
    model = scfg["model"]
    cost = 0.0

    if mode == "claude":
        if not config.anthropic_api_key():
            log(f"    [{topic}] no ANTHROPIC_API_KEY → extractive")
            mode = "claude_fallback_extractive"
        else:
            est = get_summarizer("claude", model=model).estimate(contents)
            est_cost = est.estimated_cost_usd or 0.0
            if est_cost > scfg["max_cost_usd"]:
                log(f"    [{topic}] estimate ${est_cost:.4f} > ceiling "
                    f"${scfg['max_cost_usd']:.2f} → extractive")
                mode = "claude_fallback_extractive"

    effective = "extractive" if mode == "claude_fallback_extractive" else mode
    summarizer = (
        get_summarizer("claude", model=model) if effective == "claude"
        else get_summarizer(effective)
    )
    result = summarizer.summarize(contents)
    cost = result.estimated_cost_usd or 0.0

    store.save_summary(
        topic=topic, mode=result.mode, model=result.model, document_ids=doc_ids,
        summary=result.summary, token_usage=result.token_usage, created_at=_now(),
    )
    return {"summary": result.summary, "mode": result.mode, "model": result.model, "cost": cost}


def run_digest(
    store: Store,
    topics_cfg: dict | None = None,
    *,
    out_dir: str | Path = "digests",
    date: str | None = None,
    get_source=registry.get_source,
    log=lambda *a: None,
) -> dict:
    """Fetch + summarize every configured topic and write a dated markdown digest.

    Returns {"path", "date", "topics": [per-topic result dicts], "total_cost"}.
    """
    from .cli import fetch_documents  # lazy to avoid an import cycle

    cfg = topics_cfg or config.load_topics()
    date = date or dt.date.today().isoformat()
    since = (
        dt.date.fromisoformat(date) - dt.timedelta(days=cfg["since_days"])
    ).isoformat()
    source_names = registry.resolve_sources(str(cfg["sources"]))

    topic_results: list[dict] = []
    total_cost = 0.0
    for topic in cfg["topics"]:
        log(f"  topic: {topic}")
        params = FetchParams(topic=topic, since=since, max_results=cfg["max_per_source"])
        stats = fetch_documents(store, params, source_names, get_source=get_source, log=log)
        docs = store.query_documents(topic=topic, since=since)
        if not docs:
            topic_results.append({"topic": topic, "docs": [], "summary": "(no new sources)",
                                  "mode": "none", "model": None, "cost": 0.0, "stats": stats})
            continue
        summ = _summarize_topic(store, topic, docs, cfg["summarize"], log)
        total_cost += summ["cost"]
        topic_results.append({"topic": topic, "docs": docs, "stats": stats, **summ})

    markdown = build_digest_markdown(date, since, source_names, topic_results, total_cost)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    dated = out_path / f"{date}.md"
    dated.write_text(markdown, encoding="utf-8")
    (out_path / "latest.md").write_text(markdown, encoding="utf-8")
    return {"path": str(dated), "date": date, "topics": topic_results, "total_cost": total_cost}


def build_digest_markdown(
    date: str, since: str, source_names: list[str], topic_results: list[dict], total_cost: float
) -> str:
    lines = [
        f"# AI Radar Digest — {date}",
        "",
        f"> Window: since **{since}** · sources: {', '.join(source_names)} · "
        f"est. summarization cost: **${total_cost:.4f}**",
        "",
        "## Topics",
        "",
    ]
    for r in topic_results:
        anchor = _anchor(r["topic"])
        lines.append(f"- [{r['topic']}](#{anchor}) — {len(r['docs'])} source(s)")
    lines.append("")

    for r in topic_results:
        lines += [f"## {r['topic']}", ""]
        meta = f"*{len(r['docs'])} source(s)*"
        if r["mode"] not in ("none",):
            meta += f" · *summary: {r['mode']}{'/' + r['model'] if r['model'] else ''}*"
        lines += [meta, "", r["summary"], ""]
        if r["docs"]:
            lines += ["### Sources", ""]
            for d in r["docs"]:
                d_date = d.get("publish_date") or (d.get("fetched_at") or "")[:10]
                title = d.get("title") or d["url"]
                author = d.get("author") or "unknown"
                lines.append(f"- [{title}]({d['url']}) — {d['source']} · {author} · {d_date}")
            lines.append("")
    return "\n".join(lines)


def _anchor(topic: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in topic.lower()).strip("-")
