"""Scheduled digest: fetch topics, summarize each source, and write one markdown briefing.

Map-reduce + curated:
  map     — per-document structured summary (main idea + key findings), cached on the row
  reduce  — per-topic "state of the field" synthesis from those briefs
  reduce² — a cross-topic executive summary atop the digest
The digest highlights the top ~N curated items per topic (with Related cross-links); the
exhaustive list lives in the wiki/site. Runs unattended, so the LLM path never prompts and
is bounded by a per-run cost ceiling, falling back to free extractive summaries without a key.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import config, rank
from .models import FetchParams
from .sources import registry
from .storage import Store
from .summarize import get_summarizer
from .summarize.structured import DocumentSummarizer

CURATED_PER_TOPIC = 6
RELATED_PER_ITEM = 3


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_digest(
    store: Store,
    topics_cfg: dict | None = None,
    *,
    out_dir: str | Path = "digests",
    date: str | None = None,
    get_source=registry.get_source,
    summarizer: DocumentSummarizer | None = None,
    log=lambda *a: None,
) -> dict:
    """Fetch + summarize every configured topic and write a curated markdown digest."""
    from .cli import fetch_documents  # lazy to avoid an import cycle

    cfg = topics_cfg or config.load_topics()
    scfg = cfg["summarize"]
    date = date or dt.date.today().isoformat()
    today = dt.date.fromisoformat(date)
    since = (today - dt.timedelta(days=cfg["since_days"])).isoformat()
    source_names = registry.resolve_sources(str(cfg["sources"]))

    # One LLM summarizer for the whole run so the budget ceiling is global.
    if summarizer is None and scfg["mode"] == "claude":
        s = DocumentSummarizer(scfg["model"])
        summarizer = s if s.available else None
        if summarizer is None:
            log("  no ANTHROPIC_API_KEY → extractive summaries")
    budget = float(scfg.get("max_cost_usd", 5.0))

    topic_results: list[dict] = []
    topic_syntheses: dict[str, str] = {}
    for topic in cfg["topics"]:
        log(f"  topic: {topic}")
        params = FetchParams(topic=topic, since=since, max_results=cfg["max_per_source"])
        fetch_documents(store, params, source_names, get_source=get_source, log=log)

        if summarizer is not None and summarizer.cost_usd < budget:
            _summarize_window(store, summarizer, topic, since, scfg["model"], budget, log)

        docs = store.query_documents(topic=topic, since=since)
        briefs = [json.loads(d["summary_json"]) for d in docs if d.get("summary_json")]
        synthesis = _topic_synthesis(summarizer, topic, briefs, docs, budget)
        topic_syntheses[topic] = synthesis
        # Persist the topic synthesis so the wiki/site can surface it.
        if synthesis:
            mode = "claude" if (summarizer is not None and briefs) else "extractive"
            model = scfg["model"] if mode == "claude" else None
            store.save_summary(
                topic=topic, mode=mode, model=model,
                document_ids=[d["id"] for d in docs], summary=synthesis,
                token_usage=None, created_at=_now(),
            )

        curated = rank.top_items(docs, CURATED_PER_TOPIC, today=today)
        for c in curated:
            c["_brief"] = json.loads(c["summary_json"]) if c.get("summary_json") else None
            c["_related"] = store.related(c["id"], limit=RELATED_PER_ITEM)
        topic_results.append(
            {"topic": topic, "synthesis": synthesis, "curated": curated, "total": len(docs)}
        )

    overview = ""
    if summarizer is not None and summarizer.cost_usd < budget:
        overview = summarizer.synthesize_overview(topic_syntheses)

    markdown = build_digest_markdown(date, since, source_names, overview, topic_results)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{date}.md").write_text(markdown, encoding="utf-8")
    (out / "latest.md").write_text(markdown, encoding="utf-8")
    cost = summarizer.cost_usd if summarizer else 0.0
    return {"path": str(out / f"{date}.md"), "date": date, "topics": topic_results,
            "cost_usd": cost}


def _summarize_window(store, summarizer, topic, since, model, budget, log) -> None:
    """Per-doc structured summaries for uncached docs in the window, up to the budget."""
    pending = store.unsummarized_documents(model=model, topic=topic, since=since)
    for d in pending:
        if summarizer.cost_usd >= budget:
            log(f"    budget ${budget:.2f} reached — deferring {len(pending)} summaries")
            break
        try:
            brief = summarizer.summarize_document(d["content"], d["content_type"])
        except Exception as exc:  # one bad doc shouldn't kill the run
            log(f"    ! summary failed for #{d['id']}: {exc}")
            continue
        store.save_doc_summary(d["id"], summary_json=json.dumps(brief), model=model, at=_now())


def _topic_synthesis(summarizer, topic, briefs, docs, budget) -> str:
    if summarizer is not None and briefs and summarizer.cost_usd < budget:
        try:
            return summarizer.synthesize_topic(topic, briefs)
        except Exception:
            pass
    # Free fallback: extractive over the raw contents.
    contents = [d["content"] for d in docs]
    if not contents:
        return ""
    return get_summarizer("extractive").summarize(contents).summary


# --- rendering -------------------------------------------------------------

def build_digest_markdown(date, since, source_names, overview, topic_results) -> str:
    lines = [
        f"# AI Radar Digest — {date}",
        "",
        f"> Window since **{since}** · sources: {', '.join(source_names)}",
        "",
    ]
    if overview:
        lines += ["## Executive summary", "", overview, ""]

    lines += ["## Topics", ""]
    for r in topic_results:
        lines.append(f"- [{r['topic']}](#{_anchor(r['topic'])}) — {r['total']} source(s)")
    lines.append("")

    for r in topic_results:
        lines += [f"## {r['topic']}", ""]
        if r["synthesis"]:
            lines += [r["synthesis"], ""]
        for c in r["curated"]:
            lines += _render_item(c)
        extra = r["total"] - len(r["curated"])
        if extra > 0:
            lines += [f"*+{extra} more in the [wiki](../wiki/{_anchor(r['topic'])}.md)*", ""]
    return "\n".join(lines)


def _render_item(c: dict) -> list[str]:
    title = c.get("title") or c["url"]
    date = c.get("publish_date") or (c.get("fetched_at") or "")[:10]
    out = [f"### [{title}]({c['url']})", f"*{c['source']} · {c.get('author') or 'unknown'} · {date}*", ""]
    brief = c.get("_brief")
    if brief:
        if brief.get("main_idea"):
            out += [f"**Main idea:** {brief['main_idea']}", ""]
        if brief.get("key_findings"):
            out += ["**Key findings:**"] + [f"- {f}" for f in brief["key_findings"]] + [""]
        if brief.get("why_it_matters"):
            out += [f"**Why it matters:** {brief['why_it_matters']}", ""]
    else:
        snippet = (c.get("content") or "").strip()[:240]
        if snippet:
            out += [snippet, ""]
    related = c.get("_related") or []
    if related:
        links = " · ".join(f"[{(d.get('title') or d['url'])[:60]}]({d['url']})" for d in related)
        out += [f"**Related:** {links}", ""]
    return out


def _anchor(topic: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in topic.lower()).strip("-")
