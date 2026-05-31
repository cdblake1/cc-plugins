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
#   SCHEDULE_MODE      "loop" (default; self-schedules) or "once" (for cron/scheduled machines)
#   INTERVAL_SECONDS   loop interval (default 86400 = daily)
set -euo pipefail

export AI_RADAR_DB="${AI_RADAR_DB:-/data/store.db}"
DIGEST_SUBDIR="${DIGEST_SUBDIR:-ai-radar/digests}"
GIT_NAME="${GIT_NAME:-ai-radar-bot}"
GIT_EMAIL="${GIT_EMAIL:-ai-radar-bot@users.noreply.github.com}"

run_once() {
  echo "[ai-radar] run starting $(date -u +%FT%TZ)"
  if [ -n "${GIT_REPO_URL:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
    local repo=/data/repo
    if [ ! -d "$repo/.git" ]; then
      git clone "https://x-access-token:${GITHUB_TOKEN}@${GIT_REPO_URL}" "$repo"
    else
      git -C "$repo" pull --ff-only || true
    fi
    local out="$repo/${DIGEST_SUBDIR}"
    mkdir -p "$out"
    ai-radar digest --out-dir "$out"
    git -C "$repo" add -A
    if ! git -C "$repo" diff --cached --quiet; then
      git -C "$repo" -c user.name="$GIT_NAME" -c user.email="$GIT_EMAIL" \
        commit -m "ai-radar digest $(date -u +%F)"
      git -C "$repo" push
      echo "[ai-radar] digest committed and pushed"
    else
      echo "[ai-radar] no digest changes to commit"
    fi
  else
    local out="${DIGEST_DIR:-/data/digests}"
    mkdir -p "$out"
    ai-radar digest --out-dir "$out"
    echo "[ai-radar] digest written to $out (no GIT_REPO_URL/GITHUB_TOKEN → not pushed)"
  fi
  echo "[ai-radar] run finished $(date -u +%FT%TZ)"
}

if [ "${SCHEDULE_MODE:-loop}" = "once" ]; then
  run_once
else
  while true; do
    run_once || echo "[ai-radar] run failed; will retry next interval"
    sleep "${INTERVAL_SECONDS:-86400}"
  done
fi
