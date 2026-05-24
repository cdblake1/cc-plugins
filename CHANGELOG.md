# Changelog

All notable changes to the **session-journal** plugin. Dates are UTC.

## [0.2.0] — 2026-05-24
### Added
- **Dev-hygiene gating (opt-in).** A `Stop` hook runs the user-configured `format_command` /
  `lint_command` / `test_command` when Claude finishes; any non-zero exit **blocks** the turn
  (exit 2) until fixed, gated on `stop_hook_active` to avoid loops. Runs are logged to a new
  `checks` table. Off by default (no command configured → no-op).
- `userConfig` options `format_command`, `lint_command`, `test_command`.
- `/hygiene` command — run the configured checks on demand.
- Check-runner unit tests (`checks.test.ts`).

## [0.1.0] — 2026-05-24
### Added
- **session-journal** plugin (PR #1): MCP `store`/`recall` over a `node:sqlite` store, shipped
  as a self-contained esbuild bundle (zero runtime deps); journal hooks
  (SessionStart/SessionEnd → `sessions`, PostToolUse Write|Edit|MultiEdit → `edits`); Bash
  guardrail PreToolUse hook (hard-blocks `rm -rf` of dangerous targets, pipe-to-shell, and
  force-push to `main`/`master`; asks on softer risks; logs decisions); `/journal` command and
  `journal-keeper` subagent.
- `cc-plugins` marketplace; published to github.com/cdblake1/cc-plugins.

### Infrastructure (PR #2)
- CI: rebuilds the bundle and fails on drift (`git diff --exit-code`), runs guardrail unit
  tests, and `claude plugin validate --strict`.
- Extracted pure `guardrail-policy.ts` with committed tests (18 cases).
- `.gitattributes` (LF normalization) and `absWorkingDir`-pinned, byte-deterministic bundle.
