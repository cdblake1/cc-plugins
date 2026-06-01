# Build from the ai-radar/ directory:  docker build -f deploy/Dockerfile -t ai-radar .
FROM python:3.12-slim

# git: commit digests back to the repo. ca-certificates: TLS. nodejs/npm: the Claude Code
# CLI (subscription-backed summaries). curl: health checks / debugging.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Headless Claude Code CLI for summarize.backend=claude_code ($0-API subscription summaries).
RUN npm install -g @anthropic-ai/claude-code && claude --version || true

WORKDIR /app
COPY . /app

# Install with the optional Claude summarizer; keep yt-dlp current for the YouTube extractor.
RUN pip install --no-cache-dir ".[llm]" && pip install --no-cache-dir --upgrade yt-dlp

# entrypoint.sh re-invokes itself and runs deploy/server.py (http mode), so keep them together.
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY deploy/server.py /usr/local/bin/server.py
RUN chmod +x /usr/local/bin/entrypoint.sh

# Persistent store + digests live on a mounted volume by default.
ENV AI_RADAR_DB=/data/store.db
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
