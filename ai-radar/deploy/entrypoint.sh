#!/usr/bin/env bash
# AI Radar scheduled runner.
#
# Persistent SQLite store lives on the mounted volume (AI_RADAR_DB, default /data/store.db).
# Each run builds a markdown digest and, when GIT_REPO_URL + GITHUB_TOKEN are set, commits
# it back to the repo so the digest is versioned alongside the code.
#
# Env:
#   AI_RADAR_DB        SQLite path (default /data/store.db)
#   ANTHROPIC_API_KEY  enables Claude summaries (else falls back to extractive)
#   GIT_REPO_URL       e.g. github.com/cdblake1/cc-plugins.git  (no scheme)
#   GITHUB_TOKEN       token with push access to GIT_REPO_URL
#   DIGEST_SUBDIR      path within the repo for digests (default ai-radar/digests)
#   SCHEDULE_MODE      "loop" (default; self-schedules), "once" (cron/scheduled machines),
#                      or "http" (scale-to-zero: serve GET /pull & /health, run on demand)
#   INTERVAL_SECONDS   loop interval (default 86400 = daily; 604800 = weekly)
#   BACKFILL_MONTHS    if set (e.g. "6"), run a one-time historical backfill of all topics
#                      on first boot (recorded on the volume so it only happens once)
#   BACKFILL_SOURCES   sources for the one-time backfill (default: all)
#   PORT               http mode listen port (default 8080)
#   PULL_TOKEN         http mode shared secret; GET /pull must present it (?token= or Bearer)
#   YT_COOKIES         http mode: contents of a yt-dlp cookies.txt from a DEDICATED THROWAWAY
#                      Google account (never a personal one) — written to /data and exported
#                      as YT_COOKIES_FILE so the YouTube source clears the bot gate.
#   SUMMARIZER         passed to `ai-radar digest --summarizer`: "claude_code" (subscription
#                      CLI, $0 API) or "api" (metered key). Unset → topics.yaml backend.
#   CLAUDE_CODE_OAUTH_TOKEN  subscription token (claude setup-token) for SUMMARIZER=claude_code
# Running on Fly (vs GitHub Actions) gives a stable, non-shared IP, so YouTube transcript
# fetches succeed far more often than on Actions' flagged runner ranges; the title+description
# fallback still keeps coverage if a given video is blocked.
set -euo pipefail

export AI_RADAR_DB="${AI_RADAR_DB:-/data/store.db}"
DIGEST_SUBDIR="${DIGEST_SUBDIR:-ai-radar/digests}"
WIKI_SUBDIR="${WIKI_SUBDIR:-ai-radar/wiki}"
SITE_SUBDIR="${SITE_SUBDIR:-ai-radar/site}"
GIT_NAME="${GIT_NAME:-ai-radar-bot}"
GIT_EMAIL="${GIT_EMAIL:-ai-radar-bot@users.noreply.github.com}"

install_secrets() {
  # Materialize secret *contents* passed via env into files the app reads. Idempotent.
  mkdir -p /data
  if [ -n "${YT_COOKIES:-}" ] && [ ! -f /data/yt_cookies.txt ]; then
    printf '%s' "$YT_COOKIES" > /data/yt_cookies.txt
    chmod 600 /data/yt_cookies.txt
  fi
  if [ -f /data/yt_cookies.txt ]; then
    export YT_COOKIES_FILE=/data/yt_cookies.txt
  fi
}

maybe_backfill() {
  # One-time historical backfill of every configured topic, guarded by a marker on the volume.
  local marker=/data/.backfilled
  if [ -n "${BACKFILL_MONTHS:-}" ] && [ ! -f "$marker" ]; then
    echo "[ai-radar] one-time backfill: ${BACKFILL_MONTHS} months, sources=${BACKFILL_SOURCES:-all}"
    ai-radar backfill --months "$BACKFILL_MONTHS" --sources "${BACKFILL_SOURCES:-all}" || \
      echo "[ai-radar] backfill had errors (continuing)"
    date -u +%FT%TZ > "$marker"
  fi
}

run_once() {
  echo "[ai-radar] run starting $(date -u +%FT%TZ)"
  install_secrets
  maybe_backfill
  if [ -n "${GIT_REPO_URL:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
    local repo=/data/repo
    if [ ! -d "$repo/.git" ]; then
      git clone "https://x-access-token:${GITHUB_TOKEN}@${GIT_REPO_URL}" "$repo"
    else
      git -C "$repo" pull --ff-only || true
    fi
    mkdir -p "$repo/${DIGEST_SUBDIR}"
    ai-radar digest --out-dir "$repo/${DIGEST_SUBDIR}" ${SUMMARIZER:+--summarizer "$SUMMARIZER"}
    ai-radar wiki --out-dir "$repo/${WIKI_SUBDIR}"
    ai-radar site --out-dir "$repo/${SITE_SUBDIR}" --title "AI Radar"
    git -C "$repo" add -A
    if ! git -C "$repo" diff --cached --quiet; then
      git -C "$repo" -c user.name="$GIT_NAME" -c user.email="$GIT_EMAIL" \
        commit -m "ai-radar digest $(date -u +%F)"
      git -C "$repo" push
      echo "[ai-radar] digest + wiki + site committed and pushed"
    else
      echo "[ai-radar] no changes to commit"
    fi
  else
    ai-radar digest --out-dir "${DIGEST_DIR:-/data/digests}" ${SUMMARIZER:+--summarizer "$SUMMARIZER"}
    ai-radar wiki --out-dir "${WIKI_DIR:-/data/wiki}"
    ai-radar site --out-dir "${SITE_DIR:-/data/site}" --title "AI Radar"
    echo "[ai-radar] digest + wiki + site written to /data (no GIT_REPO_URL/GITHUB_TOKEN → not pushed)"
  fi
  echo "[ai-radar] run finished $(date -u +%FT%TZ)"
}

# Single-flight wrapper so overlapping triggers (an HTTP /pull while a run is in flight, or
# a loop tick) never double-run against the same store.
run_guarded() {
  local lock=/data/.run.lock
  mkdir -p /data
  if ( set -o noclobber; echo "$$" > "$lock" ) 2>/dev/null; then
    trap 'rm -f "$lock"' RETURN
    run_once || echo "[ai-radar] run failed"
  else
    echo "[ai-radar] a run is already in progress (lock held) — skipping"
  fi
}

serve_http() {
  # Scale-to-zero front door: a tiny stdlib HTTP server. GET /health → 200; GET /pull (with
  # the shared secret) → 202 and kicks run_guarded in the background so the request never
  # hangs on a multi-minute run. Fly auto-starts the machine on the inbound request and
  # auto-stops it when idle (see fly.toml), so this is "serverless" without losing the
  # dedicated IP / SQLite volume.
  install_secrets
  export PORT="${PORT:-8080}"
  echo "[ai-radar] http mode on :${PORT} (GET /pull, GET /health)"
  exec python3 "$(dirname "$0")/server.py"
}

# The http server re-invokes this script as `entrypoint.sh run-once` to do one guarded run
# in the background, independent of SCHEDULE_MODE.
if [ "${1:-}" = "run-once" ]; then
  run_guarded
  exit $?
fi

case "${SCHEDULE_MODE:-loop}" in
  once)
    run_guarded
    ;;
  http)
    serve_http
    ;;
  *)  # loop
    while true; do
      run_guarded
      sleep "${INTERVAL_SECONDS:-86400}"
    done
    ;;
esac
