"""Subscription-backed summaries via the headless Claude Code CLI (zero API spend).

This reuses the *exact* map-reduce prompts and JSON parsing of the metered
`structured.DocumentSummarizer` — it only swaps the transport: instead of calling the
Anthropic SDK (which bills a separate API wallet), it shells out to the `claude` CLI in
print mode (`claude -p`), authenticated by a Claude subscription token
(`CLAUDE_CODE_OAUTH_TOKEN`, minted once with `claude setup-token`). So the digest gets the
same structured `main_idea / key_findings / why_it_matters` briefs at $0 cash cost — the
work counts against the subscription's usage windows instead.

Fail-soft, mirroring `structured`: if the `claude` binary or the token is missing,
`available` is False and the digest falls back to free extractive summaries.

The system prompt is passed via `-p`; the document/brief payload is piped on stdin (so we
never hit argv length limits on full-text papers).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .structured import DocumentSummarizer

# Generous per-call ceiling: a single doc/topic/overview synthesis, not the whole run.
_CALL_TIMEOUT_S = int(os.environ.get("CLAUDE_CLI_TIMEOUT", "180") or "180")


def cli_bin() -> str:
    """The Claude Code executable (override with CLAUDE_CLI_BIN for tests/custom installs)."""
    return os.environ.get("CLAUDE_CLI_BIN", "claude")


def _token() -> str | None:
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    return tok or None


class ClaudeCodeSummarizer(DocumentSummarizer):
    """Drop-in for DocumentSummarizer that synthesizes via the `claude` CLI subprocess.

    cost_usd stays 0.0 (subscription, not metered API), so the per-run budget ceiling never
    trips — every uncached doc in the window is summarized each run.
    """

    def __init__(self, model: str | None = None, **_ignored):
        # model is accepted for signature compatibility but the CLI picks its own model.
        super().__init__(model or "claude-code", api_key="subscription")
        self.cost_usd = 0.0

    @property
    def available(self) -> bool:
        return shutil.which(cli_bin()) is not None and _token() is not None

    def _client_or_raise(self):  # pragma: no cover - never used on this path
        raise RuntimeError("ClaudeCodeSummarizer does not use the Anthropic SDK client")

    def _track(self, usage) -> None:  # no metered cost on the subscription path
        return None

    def _call(self, system: str, user: str, *, max_tokens: int) -> str:
        """Run `claude -p <system>` with the payload on stdin; return stdout text.

        max_tokens is ignored (the CLI manages its own output budget). Any failure raises,
        and callers in digest.py already wrap synthesis in try/except → extractive fallback.
        """
        if not self.available:
            raise RuntimeError("claude CLI or CLAUDE_CODE_OAUTH_TOKEN unavailable")
        proc = subprocess.run(
            [cli_bin(), "-p", system, "--output-format", "text"],
            input=user,
            capture_output=True,
            text=True,
            timeout=_CALL_TIMEOUT_S,
            env=os.environ.copy(),
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
            )
        return (proc.stdout or "").strip()
