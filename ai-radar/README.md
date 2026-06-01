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

## Scheduled digest

`ai-radar digest` fetches every topic in `config/topics.yaml`, summarizes each, and writes
a dated markdown digest (table of contents + per-topic source references), plus `latest.md`.

```bash
ai-radar digest --out-dir digests        # writes digests/YYYY-MM-DD.md + digests/latest.md
ai-radar digest --summarizer claude_code # summarize via a Claude subscription, $0 API
```

Summaries use the Claude map-reduce when `summarize.mode: claude` is set (the default in
`topics.yaml`), bounded by a per-run cost ceiling (`summarize.max_cost_usd`) and falling back
to free extractive summaries if no summarizer is available. The **backend** decides the
wallet — see [Summarization wallets](#summarization-wallets-api-vs-subscription) — and for
**hosting it on Fly** (recommended, especially for YouTube), see
[Hosting on Fly.io](#hosting-on-flyio-recommended).

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


## Summarization wallets (API vs subscription)

The Claude summaries can draw on either of two **separate** wallets — pick with
`summarize.backend` in `topics.yaml` or `digest --summarizer`:

| Backend | Wallet | Auth | Cost |
|---|---|---|---|
| `api` (default) | **metered Anthropic API** | `ANTHROPIC_API_KEY` | per-token $ (bounded by `max_cost_usd`) |
| `claude_code` | **your Claude subscription** | `CLAUDE_CODE_OAUTH_TOKEN` | $0 in cash — consumes your plan's usage windows |

The `claude_code` backend shells out to the headless **Claude Code CLI** (`claude -p`) using
the *same* structured map-reduce prompts as the API path, so you get identical
`main idea / key findings / why it matters` briefs without an API bill. Mint the token once:

```bash
claude setup-token        # prints a CLAUDE_CODE_OAUTH_TOKEN
```

Honest caveats: it counts against your subscription's usage limits (a fresh 6-month backfill
can throttle across windows — it waits, never bills), and needs the `claude` CLI present (the
Fly image installs it). If the CLI/token is missing it falls back to free extractive summaries.

## Hosting on Fly.io (recommended)

GitHub Actions runners share heavily-used IP ranges that YouTube frequently blocks, so on
Actions most videos fall back to title+description. **Fly.io gives the app a stable, dedicated
IP** (`fly ips allocate-v4`), so transcript fetches succeed far more often — you get real
transcripts. The whole pipeline (fetch → summarize → digest → wiki → site) runs there with a
persistent SQLite store and commits results back to the repo.

The default mode is **scale-to-zero**: the machine sleeps when idle and auto-starts on an
inbound request. An authenticated `GET /pull` kicks one run in the background; it commits, then
idles back to zero — so a stopped machine costs only the volume.

```bash
cd ai-radar
# edit fly.toml: set a unique app name (app = "...")
fly launch --no-deploy --copy-config
fly volumes create ai_radar_data --size 1            # persistent /data (store + repo clone)
fly ips allocate-v4                                  # dedicated egress IP → reliable YouTube
fly secrets set GITHUB_TOKEN=ghp_... \
                GIT_REPO_URL=github.com/cdblake1/cc-plugins.git \
                PULL_TOKEN=$(openssl rand -hex 16) \
                CLAUDE_CODE_OAUTH_TOKEN=...           # subscription summaries (claude setup-token)
fly deploy
```

Then trigger a pull (the machine wakes if asleep):

```bash
curl -H "Authorization: Bearer $PULL_TOKEN" https://<app>.fly.dev/pull   # 202 accepted
```

Point **any** scheduler at that URL — a weekly GitHub Actions cron, a phone shortcut, `cron`.
`GET /health` is unauthenticated for Fly's health check; `/pull` requires `PULL_TOKEN` (as a
Bearer header or `?token=`), is single-flight (concurrent calls return `409 busy`), and returns
immediately so it never times out on a multi-minute run.

**Weekly trigger via GitHub Actions** (`.github/workflows/ai-radar-pull.yml`, Mondays 08:00 UTC
+ a manual "Run workflow" button). It only pokes `/pull` — no pipeline runs on GitHub's
(YouTube-blocked) runners. Add two repo secrets (**Settings → Secrets and variables → Actions →
New repository secret**):

| Secret | Value |
|---|---|
| `FLY_APP_URL` | `https://<your-app>.fly.dev` (no trailing slash) |
| `PULL_TOKEN`  | the **same** value you set as the Fly `PULL_TOKEN` secret above |

Until both are set the workflow fails fast with a clear error rather than silently no-op'ing.
The older `ai-radar.yml` workflow is now **manual-only** (its daily cron was removed so it
doesn't race the Fly pull); run it on demand for one-off fetch/backfill on GitHub's open network
or to (re)publish the site to GitHub Pages.

`fly.toml` sets `BACKFILL_MONTHS=6`, so the **first run does a one-time 6-month backfill of all
topics** (guarded by a marker on the volume), then incremental runs after that. Alternatives to
scale-to-zero: `SCHEDULE_MODE=loop` (always-on; `INTERVAL_SECONDS=604800` = weekly) or
`SCHEDULE_MODE=once` (one run then exit, for a Fly scheduled machine). Without
`GIT_REPO_URL`/`GITHUB_TOKEN` it writes digest/wiki/site to `/data` instead of pushing. The same
Dockerfile runs on any VPS/Docker host.

### Ballpark cost

| | Summaries | All-in / mo | All-in / yr |
|---|---|---|---|
| **Subscription** (`claude_code`) | $0 cash* | **~$2–3** | **~$27–32** |
| Haiku API | ~$6–10 | ~$8–13 | ~$100–155 |
| Sonnet API | ~$18–22 (cap) | ~$20–25 | ~$250–300 |

\*Consumes your Claude plan's usage windows, not dollars. Fly itself ≈ volume (~$0.15/mo) +
dedicated IPv4 (~$2/mo) + near-zero scale-to-zero compute on a weekly cadence.

### YouTube without getting banned

YouTube gates datacenter IPs behind *"Sign in to confirm you're not a bot."* To pull
transcripts reliably **without risking a ban**:

- **Use cookies from a dedicated throwaway Google account — never your personal one.** If the
  cookie ever gets flagged, you lose a burner, not your real account. Export a Netscape
  `cookies.txt` ([yt-dlp guide](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp))
  and pass it as a secret: `fly secrets set YT_COOKIES="$(cat cookies.txt)"` (the entrypoint
  writes it to the volume and points `YT_COOKIES_FILE` at it). Locally, set
  `YT_COOKIES_FILE=/path/to/cookies.txt`.
- **Throttle** — `YT_SLEEP_SECONDS=2` (default in `fly.toml`) spaces requests so cookied
  traffic looks human. Request *rate*, not cookies per se, is what triggers bans.
- The **title+description fallback** still captures any video that's gated, so the digest never
  drops to zero coverage even if a cookie expires. Cookies expire periodically — re-export and
  reset the secret when YouTube coverage drops.
