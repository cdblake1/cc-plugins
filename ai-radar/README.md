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

## Search & wiki

Stored documents are indexed with SQLite **FTS5**, so search is BM25-weighted (titles
weighted above body):

```bash
ai-radar search "autonomous tool use"          # ranked hits with source links
ai-radar search "evaluation" --topic "llm eval" --json
```

Generate a **cross-linked markdown wiki** from everything stored — an index plus one page
per topic with the latest summary, linked source references, and cross-references to
related topics (computed for free from shared salient terms via the FTS index):

```bash
ai-radar wiki --out-dir wiki        # writes wiki/index.md + wiki/<topic>.md
```

Or generate a **self-contained static site** — one portable `index.html` (data embedded
inline, no build step, no external JS/CSS) with browse-by-topic, summaries, cross-links,
and a weighted client-side search box:

```bash
ai-radar site --out-dir _site       # open _site/index.html in any browser
```

### Browse on GitHub Pages (real data, zero local setup)

The workflow at `.github/workflows/ai-radar.yml` runs on GitHub's runners (open network,
so it fetches **real** sources), builds the digest + wiki + site, commits the markdown
back, and deploys the site to GitHub Pages. Trigger it from the **Actions tab → AI Radar →
Run workflow** (or wait for the daily schedule). To serve it, enable **Settings → Pages →
Source: GitHub Actions**. Even without Pages enabled, each run uploads the site as a
downloadable artifact. Add an `ANTHROPIC_API_KEY` repo secret for Claude summaries
(otherwise free extractive summaries are used).

## Backfill (historical, windowed)

To populate history, backfill iterates date windows oldest→newest (one big `--since` pull
doesn't work — sources cap results and only return the most recent matches). Re-runnable
and resumable thanks to the `UNIQUE(source, external_id)` constraint:

```bash
ai-radar backfill "agentic coding" --months 3 --window weekly
ai-radar backfill "ai engineering" --months 6 --channel @somechannel   # YouTube back-catalog
ai-radar backfill --months 3 --sources arxiv,hackernews                # omit topic = all topics.yaml
```

Omit the topic to backfill **every topic in `config/topics.yaml`** (the same list the
digest uses).

Per-source reality: **arXiv** and **Hacker News** have full date-ranged history;
**YouTube** backfills well per `--channel`; **RSS** feeds only serve recent entries (no
historical archive), so they contribute little to a backfill — that's expected.

## Scheduled daily digest + hosting (Fly.io)

`ai-radar digest` fetches every topic in `config/topics.yaml`, summarizes each, and writes
a dated markdown digest (with a table of contents and per-topic source references). The
Claude summarizer is used when `ANTHROPIC_API_KEY` is set, with a per-topic cost ceiling
(`summarize.max_cost_usd`) and automatic fallback to free extractive summarization.

```bash
ai-radar digest --out-dir digests        # writes digests/YYYY-MM-DD.md + digests/latest.md
```

To run it daily on Fly.io with a **persistent SQLite store** and the digest + wiki
**committed back to this repo**:

```bash
cd ai-radar
# edit fly.toml: set a unique app name
fly launch --no-deploy --copy-config
fly volumes create ai_radar_data --size 1                 # persistent /data volume
fly secrets set ANTHROPIC_API_KEY=sk-... \
                GITHUB_TOKEN=ghp_... \
                GIT_REPO_URL=github.com/cdblake1/cc-plugins.git
fly deploy
```

The container (`deploy/Dockerfile` + `deploy/entrypoint.sh`) self-schedules a daily run
(`SCHEDULE_MODE=loop`, `INTERVAL_SECONDS=86400`), keeps `store.db` on the `/data` volume,
and — when `GIT_REPO_URL` + `GITHUB_TOKEN` are set — commits the regenerated digest and
wiki back to the repo. Set `SCHEDULE_MODE=once` to use a Fly scheduled machine or external
cron instead. The same Dockerfile runs on any VPS/Docker host.

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
