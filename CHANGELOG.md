# Changelog

All notable changes to the **session-journal** plugin. Dates are UTC.

## [0.5.0] — 2026-05-24
### Added
- **Auto-capture (closes the capture gap).** Memory no longer depends on someone remembering to
  store a note:
  - **`/checkpoint` command** — the model writes a structured handoff (Goal / Done / Open / Next /
    Watch) and saves it under key `checkpoint`.
  - **Automatic session rollup** — the `SessionEnd` hook writes a deterministic note (files
    touched, edit count, branch/commit, duration) under key `session-rollup` whenever the session
    made edits. Pure SQLite, no model — works in headless/CI runs too. Opt out with
    userConfig `auto_rollup = "off"`.
- **Handoff at start.** The `SessionStart` auto-recall hook now leads with the most recent
  `checkpoint`/`session-rollup` ("picking up … last session: …"), then lists earlier notes — so a
  new session opens with where you left off.
- `scripts/rollup.ts` (pure rollup formatting) + unit tests (`rollup.test.ts`).

### Notes
- No schema or bundle change: `/checkpoint` reuses the existing `store` tool and the rollup writes
  to the existing `notes` table.
- Feasibility-verified beforehand: model-invoking `agent` hooks are REPL-only, but `command` hooks
  run (and `SessionEnd` blocks on them) in headless `-p` runs — hence the deterministic rollup.

## [0.4.0] — 2026-05-24
### Added
- **Guardrail hardening:** also hard-blocks fork bombs, `dd`/`mkfs` writing to a block device,
  and recursive `chmod 777` on system paths (`/`, `~`, `$HOME`).
- **`journal` MCP tool** (`mcp__session-journal__journal`): lists recent file edits for the current
  repository — the activity log is now readable, not just written.

## [0.3.0] — 2026-05-24
### Added
- **Git-aware memory.** Notes are tagged with the current repository; `recall` defaults to the
  current repo (plus un-scoped notes) with a new `scope: 'repo' | 'all'` parameter.
- **Auto-recall:** a `SessionStart` hook injects this repo's recent notes into context at the start
  of every session — cross-session memory now reaches the model without being asked.
- `sessions` rows record `repo` / `branch` / `commit_sha`.
- Guardrail force-push rule now targets the repo's **dynamically detected default branch**
  (e.g. `develop`), not just `main`/`master`.
- `scripts/gitctx.ts` (+ unit tests); first DB migration (`addColumnIfMissing`) upgrades pre-v3 stores.

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
