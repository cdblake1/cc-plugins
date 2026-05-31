# Build from the ai-radar/ directory:  docker build -f deploy/Dockerfile -t ai-radar .
FROM python:3.12-slim

# git: used by the entrypoint to commit digests back to the repo. ca-certificates: TLS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Install with the optional Claude summarizer.
RUN pip install --no-cache-dir ".[llm]"

COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Persistent store + digests live on a mounted volume by default.
ENV AI_RADAR_DB=/data/store.db
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
