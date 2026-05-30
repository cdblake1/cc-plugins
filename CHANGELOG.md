# Changelog

All notable changes to the **local-cc-plugin** plugin (formerly named `session-journal`; that
name now refers to the MCP server inside it). Dates are UTC.

## [Unreleased]
### Changed
- **Renamed the plugin `session-journal` → `local-cc-plugin`** (umbrella name; placeholder). The
  MCP server keeps the name `session-journal`, so all `mcp__session-journal__*` tool ids and the
  bundle are unchanged. Plugin dir, manifest, marketplace entry, CI paths, and docs updated.
  Note: the plugin's `${CLAUDE_PLUGIN_DATA}` id changes with the name, so existing local state is
  migrated by copying the old data dir to the new id.
### Added
- **`/init` slash command** — interactively set Claude Code's view verbosity (`viewMode`,
  `outputStyle`) in your user `settings.json`. Non-destructive and idempotent; backed by
  `scripts/apply-view-prefs.ts` (uses only `node:fs`/`os`/`path`, not part of the MCP bundle).

## [0.7.0] — 2026-05-30
### Added
- **`/clarify-intent [what you want to build]` slash command.** Stakeholder-style requirement
  gathering: the engineering team interviews you with a mix of multiple-choice (`AskUserQuestion`)
  and open-ended questions across six requirement dimensions, composes a structured requirements
  doc, then verifies it before you start building.
- **`clarify-intent` skill** — the plugin's first skill. Holds the interview methodology and the
  six dimensions (problem, users, scope, behavior, constraints, success/edge cases). Auto-triggers
  when scoping a feature or pinning down intent before code is written. Markdown-only component,
  auto-discovered from `skills/`; no bundle rebuild.
- **`requirements-verifier` subagent.** Runs on `model: haiku` with no tools and a single pass:
  reads the requirements doc inline and returns a READY/NOT-READY verdict with a per-dimension
  coverage checklist and any blocking gaps. The skill loops on gaps (capped at 2 rounds), then
  persists the final doc via `store` (`key: requirements`).

## [0.6.0] — 2026-05-26
### Added
- **`forget` MCP tool.** Delete a stored note by `id`; bulk-delete by `key` requires
  `confirm:"yes"` to avoid accidents.
- **`pin` MCP tool.** Toggle a per-note pinned flag. Pinned notes lead every SessionStart
  inject (above the checkpoint), then the handoff, then earlier notes. Use sparingly — pinned
  notes eat the recall context budget.
- **Tags on notes.** `store` accepts an optional `tags` array (lowercased + deduped); `recall`
  filters by `tags` and renders them inline. Additive `note_tags` table with `ON DELETE CASCADE`.
- **Smarter `recall`.** Full-text search over note bodies via FTS5 (`query:` is a phrase MATCH),
  plus `since` / `until` ISO date-range filters.

### Changed
- **Quieter SessionStart inject.** The "earlier notes" block now excludes `session-rollup`
  notes — they're deterministic activity dumps that crowded out hand-written context once a
  few sessions accumulated. The freshest rollup still surfaces via the handoff fallback when
  no `/checkpoint` exists.
- **Bounded rollup growth.** `SessionEnd` now prunes older `session-rollup` notes per repo,
  keeping the most recent 5 (pinned rollups always preserved). Raw activity remains searchable
  via the `edits` table; the `journal` MCP tool is unaffected. New `pruneOldRollups` helper +
  tests.

### Schema
- `notes.pinned` column (added via `addColumnIfMissing`).
- `note_tags(note_id, tag)` table + `idx_note_tags_tag` index.
- `notes_fts` external-content FTS5 virtual table + insert/update/delete sync triggers,
  with a one-time backfill gated on `PRAGMA user_version < 6`.

### Refactor
- MCP tool bodies extracted to `mcp/handlers.ts` (pure-ish, take a `DatabaseSync`). Mirrors the
  `guardrail-policy.ts` / `rollup.ts` pattern; enables direct unit testing without spawning the
  bundle.

## [0.5.1] — 2026-05-24
### Fixed
- **Handoff now leads with your `/checkpoint`, not the auto rollup.** The `SessionStart` handoff
  picked the most recent of `checkpoint`/`session-rollup` by recency, so the rollup written at
  `SessionEnd` (newer) shadowed the checkpoint from the same session. It now prefers `checkpoint`
  and only falls back to `session-rollup` when no checkpoint exists in scope.
- **Rollup no longer lists deleted files.** The `SessionEnd` rollup filtered nothing, so scratch/
  temp files created and deleted within a session still appeared. Edits to files that no longer
  exist at session end are now dropped (new pure `liveEdits` helper + tests).

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
