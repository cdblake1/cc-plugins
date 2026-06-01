#!/usr/bin/env python3
"""Tiny scale-to-zero HTTP front door for the AI Radar runner (stdlib only).

Routes:
  GET /health  -> 200 "ok"            (Fly health check; cheap, no auth)
  GET /pull    -> 202 "accepted"      (kick a run in the background) — requires the shared
                  401 "unauthorized"   secret in ?token= or an "Authorization: Bearer ..." header
                  409 "busy"           if a run is already in flight (lockfile present)

The actual work is `entrypoint.sh run-once` spawned detached, so the HTTP response returns
immediately and never times out on a multi-minute fetch+summarize+commit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("PORT", "8080") or "8080")
LOCK = "/data/.run.lock"
ENTRYPOINT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entrypoint.sh")


def _expected_token() -> str:
    return (os.environ.get("PULL_TOKEN", "") or "").strip()


def _presented_token(handler: "Handler") -> str:
    auth = handler.headers.get("Authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    qs = parse_qs(urlparse(handler.path).query)
    return (qs.get("token", [""])[0] or "").strip()


def _authorized(handler: "Handler") -> bool:
    want = _expected_token()
    # If no token is configured, refuse /pull rather than expose an open trigger.
    return bool(want) and _presented_token(handler) == want


def _kick_run() -> None:
    """Spawn a detached run via the entrypoint's run-once path."""
    subprocess.Popen(
        ["bash", ENTRYPOINT, "run-once"],
        stdout=sys.stdout, stderr=sys.stderr,
        start_new_session=True,
    )


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._reply(200, "ok")
            return
        if path == "/pull":
            if not _authorized(self):
                self._reply(401, "unauthorized")
                return
            if os.path.exists(LOCK):
                self._reply(409, "busy: a run is already in progress")
                return
            _kick_run()
            self._reply(202, "accepted: run started")
            return
        self._reply(404, "not found")

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        sys.stderr.write("[ai-radar.http] " + (fmt % args) + "\n")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[ai-radar.http] listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
