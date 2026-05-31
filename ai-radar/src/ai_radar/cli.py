"""Command-line interface: fetch / list / summarize / export / sources.

Orchestration logic is factored into small functions (fetch_documents, run_summarize) so
it can be unit-tested without spawning a process or hitting the network.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from . import config
from .models import Document, FetchParams, Run
from .sources import registry
from .sources.base import ContentUnavailable
from .storage import Store
from .summarize import get_summarizer


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --- orchestration ---------------------------------------------------------

def fetch_documents(
    store: Store,
    params: FetchParams,
    source_names: list[str],
    *,
    get_source=registry.get_source,
    log=lambda *a: None,
) -> dict:
    """Run discovery + content fetch across sources and persist documents.

    Returns {"run_id", "inserted", "duplicate", "skipped"}.
    """
    run = Run(
        topic=params.topic,
        sources=",".join(source_names),
        params_json=json.dumps(
            {
                "since": params.since,
                "max_results": params.max_results,
                "channel": params.channel,
                "lang": params.lang,
            }
        ),
        started_at=_now(),
    )
    run_id = store.start_run(run)

    inserted = duplicate = skipped = 0
    for name in source_names:
        try:
            source = get_source(name)
        except Exception as exc:  # unknown/broken source — don't abort the run
            log(f"  ! source {name} unavailable: {exc}")
            continue
        try:
            items = source.discover(params)
        except Exception as exc:
            log(f"  ! {name} discovery failed: {exc}")
            continue
        log(f"  {name}: discovered {len(items)} item(s)")
        for item in items:
            try:
                content, lang = source.fetch_content(item)
            except ContentUnavailable:
                skipped += 1
                continue
            except Exception as exc:
                log(f"    ! {name} fetch failed for {item.external_id}: {exc}")
                skipped += 1
                continue
            doc = Document(
                source=item.source,
                content_type=item.content_type,
                external_id=item.external_id,
                url=item.url,
                topic=params.topic,
                content=content,
                fetched_at=_now(),
                title=item.title,
                author=item.author,
                publish_date=item.publish_date,
                lang=lang or params.lang,
                meta=item.meta,
                run_id=run_id,
            )
            if store.upsert_document(doc):
                inserted += 1
            else:
                duplicate += 1

    store.finish_run(run_id, finished_at=_now(), item_count=inserted, status="ok")
    return {"run_id": run_id, "inserted": inserted, "duplicate": duplicate, "skipped": skipped}


def run_summarize(
    store: Store,
    topic: str,
    mode: str,
    *,
    model: str = config.DEFAULT_MODEL,
    max_input_docs: int | None = None,
    estimate_only: bool = False,
    confirm=lambda prompt: False,
    out=sys.stdout,
) -> dict:
    """Summarize stored documents for a topic.

    For the paid `claude` mode: always prints an estimate first; only calls the API after
    `confirm()` returns True (or never, if estimate_only). Saves the result to summaries.
    """
    rows = store.query_documents(topic=topic, limit=max_input_docs)
    if not rows:
        print(f"No documents stored for topic {topic!r}. Run `fetch` first.", file=out)
        return {"status": "no-documents"}

    docs = [r["content"] for r in rows]
    doc_ids = [r["id"] for r in rows]
    summarizer = get_summarizer(mode, model=model) if mode == "claude" else get_summarizer(mode)

    est = summarizer.estimate(docs)
    if mode == "claude":
        print(
            f"Estimate ({model}): ~{est.token_usage['input']} in + "
            f"~{est.token_usage['output']} out tokens over {len(docs)} docs "
            f"≈ ${est.estimated_cost_usd:.4f} (verify live pricing).",
            file=out,
        )
        if estimate_only:
            return {"status": "estimate-only", "estimate": est.estimated_cost_usd}
        if not confirm(f"Proceed with paid {model} summarization? [y/N] "):
            print("Aborted before any API call.", file=out)
            return {"status": "aborted", "estimate": est.estimated_cost_usd}

    result = summarizer.summarize(docs)
    summary_id = store.save_summary(
        topic=topic,
        mode=result.mode,
        model=result.model,
        document_ids=doc_ids,
        summary=result.summary,
        token_usage=result.token_usage,
        created_at=_now(),
    )
    print(result.summary, file=out)
    return {
        "status": "ok",
        "summary_id": summary_id,
        "mode": result.mode,
        "model": result.model,
        "token_usage": result.token_usage,
        "cost_usd": result.estimated_cost_usd,
    }


# --- command handlers ------------------------------------------------------

def _open_store(args) -> Store:
    return Store.open(args.db or str(config.db_path()))


def cmd_fetch(args) -> int:
    store = _open_store(args)
    try:
        names = registry.resolve_sources(args.sources)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    params = FetchParams(
        topic=args.topic,
        since=args.since,
        max_results=args.max,
        channel=args.channel,
        lang=args.lang,
    )
    print(f"Fetching '{args.topic}' from: {', '.join(names)}")
    stats = fetch_documents(store, params, names, log=lambda m: print(m))
    print(
        f"Done. run #{stats['run_id']}: {stats['inserted']} new, "
        f"{stats['duplicate']} duplicate, {stats['skipped']} skipped."
    )
    if args.summarize and stats["inserted"] + stats["duplicate"] > 0:
        run_summarize(store, args.topic, args.mode, model=args.model,
                      confirm=_tty_confirm, estimate_only=False)
    store.close()
    return 0


def cmd_list(args) -> int:
    store = _open_store(args)
    rows = store.query_documents(
        topic=args.topic, source=args.source, run_id=args.run, limit=args.limit
    )
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        if not rows:
            print("(no documents)")
        for r in rows:
            date = r.get("publish_date") or (r.get("fetched_at") or "")[:10]
            print(f"[{r['source']:<10}] {date}  {r.get('title') or r['url']}")
            print(f"             {r['url']}")
    store.close()
    return 0


def cmd_summarize(args) -> int:
    store = _open_store(args)
    run_summarize(
        store,
        args.topic,
        args.mode,
        model=args.model,
        max_input_docs=args.max_input,
        estimate_only=args.estimate_only,
        confirm=_tty_confirm,
    )
    store.close()
    return 0


def cmd_export(args) -> int:
    store = _open_store(args)
    rows = store.query_documents(topic=args.topic)
    summary = store.latest_summary(args.topic)
    payload = _render_export(args.topic, rows, summary, args.format)
    if args.out and args.out != "-":
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"Wrote {len(rows)} document(s) to {args.out}")
    else:
        print(payload)
    store.close()
    return 0


def cmd_digest(args) -> int:
    from .digest import run_digest

    store = _open_store(args)
    print(f"Building digest → {args.out_dir}")
    result = run_digest(store, out_dir=args.out_dir, date=args.date, log=lambda m: print(m))
    print(
        f"Wrote {result['path']} ({len(result['topics'])} topics, "
        f"est. cost ${result['total_cost']:.4f})"
    )
    store.close()
    return 0


def cmd_sources(args) -> int:
    feeds = config.load_feeds()
    print(f"DB: {args.db or config.db_path()}")
    print(f"Sources available: {', '.join(registry.ALL_SOURCES)}\n")
    print(f"arXiv categories: {', '.join(feeds.get('arxiv_categories', [])) or '(none)'}\n")
    print("RSS feeds (news + creator/lab blogs):")
    for f in feeds.get("rss_feeds", []):
        print(f"  - {f['name']}: {f['url']}")
    yt = feeds.get("youtube_channels", [])
    print(f"\nYouTube channel allowlist: {', '.join(yt) if yt else '(empty — topic search)'}")
    print(f"Hacker News: {feeds.get('hackernews', {})}")
    return 0


# --- helpers ---------------------------------------------------------------

def _tty_confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _render_export(topic: str, rows: list[dict], summary: dict | None, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(
            {"topic": topic, "documents": rows, "summary": summary}, indent=2, default=str
        )
    if fmt == "txt":
        lines = [f"Topic: {topic}", ""]
        if summary:
            lines += ["== Summary ==", summary["summary"], ""]
        for r in rows:
            lines += [f"# {r.get('title') or r['url']} ({r['source']})", r["content"], ""]
        return "\n".join(lines)
    # markdown (default)
    lines = [f"# AI Radar — {topic}", ""]
    if summary:
        lines += [f"## Summary ({summary['mode']})", "", summary["summary"], ""]
    lines += [f"## Documents ({len(rows)})", ""]
    for r in rows:
        date = r.get("publish_date") or (r.get("fetched_at") or "")[:10]
        lines += [
            f"### {r.get('title') or r['url']}",
            f"*{r['source']} · {r.get('author') or 'unknown'} · {date}* — <{r['url']}>",
            "",
            r["content"],
            "",
        ]
    return "\n".join(lines)


# --- argparse --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-radar", description="Multi-source AI intelligence aggregator.")
    p.add_argument("--db", help="SQLite store path (default: ~/.local/share/ai-radar/store.db)")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="fetch latest content on a topic")
    f.add_argument("topic")
    f.add_argument("--since", help="ISO date lower bound, e.g. 2026-05-01")
    f.add_argument("--max", type=int, default=10, help="max results per source")
    f.add_argument("--channel", help="source-specific filter (channel/feed/author)")
    f.add_argument("--sources", default="all",
                   help="all or comma list: arxiv,rss,hackernews,youtube")
    f.add_argument("--lang", help="preferred content language, e.g. en")
    f.add_argument("--summarize", action="store_true", help="summarize after fetching")
    f.add_argument("--mode", default="extractive", choices=["extractive", "emit", "claude"])
    f.add_argument("--model", default=config.DEFAULT_MODEL)
    f.set_defaults(func=cmd_fetch)

    l = sub.add_parser("list", help="list stored documents")
    l.add_argument("--topic")
    l.add_argument("--source")
    l.add_argument("--run", type=int)
    l.add_argument("--limit", type=int)
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("summarize", help="summarize stored documents for a topic")
    s.add_argument("topic")
    s.add_argument("--mode", default="extractive", choices=["extractive", "emit", "claude"])
    s.add_argument("--model", default=config.DEFAULT_MODEL)
    s.add_argument("--max-input", type=int, dest="max_input", help="cap docs fed in")
    s.add_argument("--estimate-only", action="store_true",
                   help="print cost estimate and stop (never calls the API)")
    s.set_defaults(func=cmd_summarize)

    e = sub.add_parser("export", help="export documents (+ latest summary) for a topic")
    e.add_argument("topic")
    e.add_argument("--format", default="md", choices=["md", "json", "txt"])
    e.add_argument("--out", default="-", help="output path, or - for stdout")
    e.set_defaults(func=cmd_export)

    d = sub.add_parser("digest", help="fetch all configured topics and write a markdown digest")
    d.add_argument("--out-dir", default="digests", help="directory for the digest markdown")
    d.add_argument("--date", help="digest date (YYYY-MM-DD); defaults to today")
    d.set_defaults(func=cmd_digest)

    sub.add_parser("sources", help="show the curated source config in use").set_defaults(
        func=cmd_sources
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
