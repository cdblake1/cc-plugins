"""Static site generator: one self-contained, dependency-free index.html.

Reads the store and emits a single HTML file with the data embedded inline (so it works
over file:// and on GitHub Pages with zero build step), offering: browse-by-topic with
summaries + source references, cross-links between related topics, and a client-side
ranked search box. No external JS/CSS/CDN.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .storage import Store
from .textutil import top_terms
from .wiki import related_topics, slug


def _load_brief(doc: dict) -> dict | None:
    raw = doc.get("summary_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _site_doc(store: Store, d: dict) -> dict:
    brief = _load_brief(d) or {}
    return {
        "title": d.get("title") or d["url"],
        "url": d["url"],
        "source": d["source"],
        "author": d.get("author") or "",
        "date": d.get("publish_date") or (d.get("fetched_at") or "")[:10],
        "snippet": (d.get("content") or "")[:240],
        "main_idea": brief.get("main_idea", ""),
        "key_findings": brief.get("key_findings", []),
        "related": [
            {"title": (r.get("title") or r["url"])[:70], "url": r["url"], "topic": r["topic"]}
            for r in store.related(d["id"], limit=3)
        ],
    }


def build_site(store: Store, out_dir: str | Path, *, title: str = "AI Radar") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    topics = store.distinct_topics()
    docs_by_topic: dict[str, list[dict]] = {t: store.query_documents(topic=t) for t in topics}
    term_map = {
        t: set(top_terms(" ".join(f"{d.get('title') or ''} {d['content']}" for d in docs), 20))
        for t, docs in docs_by_topic.items()
    }

    data = {
        "title": title,
        "topics": [
            {
                "name": t,
                "slug": slug(t),
                "summary": (store.latest_summary(t) or {}).get("summary", ""),
                "summary_mode": (store.latest_summary(t) or {}).get("mode", ""),
                "related": [
                    {"name": o, "slug": slug(o), "shared": n}
                    for o, n in related_topics(term_map, t)
                ],
                "docs": [_site_doc(store, d) for d in docs_by_topic[t]],
            }
            for t in topics
        ],
    }
    total_docs = sum(len(t["docs"]) for t in data["topics"])

    page = _TEMPLATE.replace("__TITLE__", html.escape(title))
    page = page.replace("__TOTALS__", f"{len(topics)} topics · {total_docs} sources")
    page = page.replace("__DATA__", json.dumps(data))
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")

    # .nojekyll so GitHub Pages serves files verbatim (no Jekyll processing).
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"index": str(index), "topics": len(topics), "documents": total_docs}


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#0d1117; --card:#161b22; --fg:#e6edf3; --muted:#8b949e; --accent:#58a6ff;
          --border:#30363d; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--fg); }
  header { padding:24px 20px; border-bottom:1px solid var(--border); position:sticky; top:0;
           background:var(--bg); z-index:10; }
  h1 { margin:0 0 4px; font-size:20px; } h1 span { color:var(--accent); }
  .meta { color:var(--muted); font-size:13px; }
  #q { margin-top:14px; width:100%; max-width:560px; padding:10px 12px; border-radius:8px;
       border:1px solid var(--border); background:var(--card); color:var(--fg); font-size:15px; }
  .wrap { display:flex; gap:24px; padding:20px; max-width:1100px; margin:0 auto; }
  nav { flex:0 0 220px; } nav a { display:block; color:var(--fg); text-decoration:none;
        padding:6px 8px; border-radius:6px; font-size:14px; } nav a:hover { background:var(--card); }
  nav a small { color:var(--muted); }
  main { flex:1; min-width:0; }
  .topic { background:var(--card); border:1px solid var(--border); border-radius:10px;
           padding:16px 18px; margin-bottom:18px; }
  .topic h2 { margin:0 0 8px; font-size:18px; }
  .summary { white-space:pre-wrap; color:var(--fg); background:#0d1117; border:1px solid var(--border);
             border-radius:8px; padding:10px 12px; margin:8px 0; font-size:14px; }
  .related { font-size:13px; color:var(--muted); margin:6px 0 10px; }
  .related a { color:var(--accent); text-decoration:none; }
  .doc { padding:8px 0; border-top:1px solid var(--border); }
  .doc a { color:var(--accent); text-decoration:none; font-weight:600; }
  .doc .d-meta { color:var(--muted); font-size:12px; margin:2px 0; }
  .doc .d-snip { color:var(--fg); font-size:13px; opacity:.85; }
  .doc .d-idea { color:var(--fg); font-size:13px; margin:4px 0; }
  .doc .d-idea b, .doc .d-find-h { color:var(--accent); }
  .doc .d-find { margin:4px 0 4px 18px; padding:0; font-size:13px; color:var(--fg); opacity:.9; }
  .doc .d-find li { margin:1px 0; }
  .doc .d-rel { font-size:12px; color:var(--muted); margin-top:4px; }
  .doc .d-rel a { color:var(--accent); text-decoration:none; }
  .badge { display:inline-block; font-size:11px; padding:1px 6px; border-radius:10px;
           border:1px solid var(--border); color:var(--muted); margin-right:6px; }
  .hidden { display:none; } mark { background:#473d12; color:#f2cc60; }
  footer { color:var(--muted); font-size:12px; text-align:center; padding:24px; }
</style>
</head>
<body>
<header>
  <h1><span>AI</span> Radar</h1>
  <div class="meta">__TOTALS__ · weighted client-side search</div>
  <input id="q" type="search" placeholder="Search titles &amp; sources… (e.g. agentic coding, RAG, evals)" autocomplete="off">
</header>
<div class="wrap">
  <nav id="nav"></nav>
  <main id="main"></main>
</div>
<footer>Generated by AI Radar · static, self-contained, no tracking</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const main = document.getElementById('main'), nav = document.getElementById('nav'), q = document.getElementById('q');
const STOP = new Set("the a an and or for to of in on at by with from as is are was were be this that it its".split(" "));
function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
function terms(s){return (s||'').toLowerCase().match(/[a-z0-9'+-]{3,}/g)||[];}

function renderNav(){
  nav.innerHTML = DATA.topics.map(t =>
    `<a href="#${t.slug}"><small>${t.docs.length}</small> &nbsp;${esc(t.name)}</a>`).join('');
}
function topicHTML(t){
  const rel = t.related.length
    ? `<div class="related">Related: ` +
       t.related.map(r=>`<a href="#${r.slug}">${esc(r.name)}</a>`).join(' · ') + `</div>` : '';
  const summary = t.summary ? `<div class="summary">${esc(t.summary)}</div>` : '';
  const docs = t.docs.map(d => docHTML(d)).join('');
  return `<section class="topic" id="${t.slug}"><h2>${esc(t.name)}</h2>${summary}${rel}${docs}</section>`;
}
function docHTML(d, topicName){
  const idea = d.main_idea ? `<div class="d-idea"><b>Main idea:</b> ${esc(d.main_idea)}</div>` : '';
  const finds = (d.key_findings && d.key_findings.length)
    ? `<div class="d-find-h" style="font-size:13px;font-weight:600;">Key findings</div>`
      + `<ul class="d-find">` + d.key_findings.map(f=>`<li>${esc(f)}</li>`).join('') + `</ul>`
    : '';
  const body = (idea || finds) ? (idea + finds) : `<div class="d-snip">${esc(d.snippet)}</div>`;
  const rel = (d.related && d.related.length)
    ? `<div class="d-rel">Related: ` +
       d.related.map(r=>`<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>`).join(' · ') +
       `</div>` : '';
  const meta = topicName
    ? `<span class="badge">${esc(d.source)}</span>${esc(topicName)} · ${esc(d.date)}`
    : `<span class="badge">${esc(d.source)}</span>${esc(d.author)} · ${esc(d.date)}`;
  return `
    <div class="doc">
      <a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a>
      <div class="d-meta">${meta}</div>
      ${body}${rel}
    </div>`;
}
function renderAll(){ main.innerHTML = DATA.topics.map(topicHTML).join(''); }

function search(query){
  const qs = terms(query).filter(w=>!STOP.has(w));
  if(!qs.length){ renderAll(); return; }
  const hits = [];
  for(const t of DATA.topics){
    for(const d of t.docs){
      const findText = (d.key_findings||[]).join(' ');
      const hay = (d.title+' '+d.snippet+' '+(d.main_idea||'')+' '+findText+' '+t.name).toLowerCase();
      let score = 0;
      for(const w of qs){ const inT=(d.title||'').toLowerCase().includes(w);
        if(hay.includes(w)) score += inT ? 3 : 1; }
      if(score>0) hits.push({d,t,score});
    }
  }
  hits.sort((a,b)=>b.score-a.score);
  main.innerHTML = hits.length
    ? `<section class="topic"><h2>${hits.length} result(s)</h2>`
      + hits.map(h=>docHTML(h.d, h.t.name)).join('') + `</section>`
    : `<section class="topic"><h2>No results</h2></section>`;
}
let timer; q.addEventListener('input', ()=>{ clearTimeout(timer); timer=setTimeout(()=>search(q.value),120); });
renderNav(); renderAll();
</script>
</body>
</html>
"""
