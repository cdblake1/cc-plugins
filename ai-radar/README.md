# AI Radar

A standalone CLI that pulls the **latest content on AI topics** from multiple authoritative
sources, stores it locally, and summarizes the learnings. Built for keeping up with
**software development / AI engineering / AI news / research breakthroughs / model & tooling
updates**.

Sources in v1 (all **free, no API key** by default):

| Source | What it pulls | How |
|---|---|---|
| **arxiv** | research papers / breakthroughs | arXiv Atom API (cs.AI, cs.LG, cs.CL, …) |
| **rss** | AI news **and** key creator/lab blogs | curated `config/feeds.yaml` (editable) |
| **hackernews** | trending AI/dev news & discussion | HN Algolia Search API |
| **youtube** | video transcripts | yt-dlp + youtube-transcript-api |

New sources drop in behind one `Source` interface — see `src/ai_radar/sources/base.py`.

## Install

```bash
cd ai-radar
python -m venv .venv && . .venv/bin/activate
pip install -e .            # add ".[llm]" for the optional Claude summarizer
pip install -e ".[dev]"     # to run the tests
```

Requires Python ≥ 3.10.

## Usage

```bash
ai-radar sources                                  # show the curated source list in use

# Fetch the latest on a topic across all four sources
ai-radar fetch "agentic coding" --since 2026-05-01 --max 5
ai-radar fetch "rag evaluation" --sources arxiv,rss     # only some sources

# Review what was stored
ai-radar list --topic "agentic coding"
ai-radar list --topic "agentic coding" --json

# Summarize (free modes)
ai-radar summarize "agentic coding"                       # extractive (local, $0)
ai-radar summarize "agentic coding" --mode emit > digest.md  # digest for an agent, $0

# Export
ai-radar export "agentic coding" --format md --out digest.md
```

`fetch` parameters: `--since` (ISO date), `--max` (per source), `--channel`
(source-specific filter), `--sources` (`all` or a comma list), `--lang`, and `--summarize`
to summarize right after fetching. The store defaults to
`~/.local/share/ai-radar/store.db` (override with `--db` or `AI_RADAR_DB`).

## Cost-aware Claude summarization (opt-in)

Two summarize modes are always free: **extractive** (local key-sentence extraction) and
**emit** (bundles documents into a digest for an agent like Claude Code to summarize). A
third, **claude**, calls the Anthropic API — and it **always prints a cost estimate first**
and only spends after you confirm:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=sk-...

ai-radar summarize "agentic coding" --mode claude --estimate-only   # prints $ estimate, no call
ai-radar summarize "agentic coding" --mode claude                   # estimate, then asks y/N
ai-radar summarize "agentic coding" --mode claude --model claude-sonnet-4-6
```

Ballpark (verify live pricing — see the `PRICING` table in `config.py`): avg document
≈ 3k tokens; a 50-document digest costs roughly **$0.30 on Haiku**, **~$1 on Sonnet**.
Actual token usage is recorded per run.

## Behind a TLS-intercepting corporate proxy?

All outbound HTTP funnels through `src/ai_radar/net.py`. If your network does TLS
interception, point these env vars at your setup so HTTPS verifies (verification is never
disabled by default):

```bash
export HTTPS_PROXY=http://proxy.corp:8080
export CA_BUNDLE=/etc/ssl/certs/corp-root-ca.pem
```

## Development

```bash
pip install -e ".[dev]"
pytest                      # fully offline — network and the Anthropic SDK are mocked
```

Layout: `sources/` (pluggable fetchers), `summarize/` (strategies; the Claude call is
isolated in `summarize/claude.py`), `storage.py` (SQLite DAO), `cli.py` (orchestration),
`net.py` (proxy/CA), `config/feeds.yaml` (curated sources).
