# CLAUDE.md — Claude Code Plugin Build

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands (run from `local-cc-plugin/`)
Requires **Node >= 22.6.0** (built-in `node:sqlite` + `--experimental-strip-types`).
- **All tests:** `npm test` (runs the `*.test.ts` files via `node --experimental-strip-types`).
- **One test file:** `node --experimental-strip-types --no-warnings scripts/guardrail.test.ts` (swap the path; e.g. `mcp/handlers.test.ts`).
- **Build the MCP bundle:** `npm run build` (esbuild → `mcp/server.bundle.mjs`).
- **Install build deps** (behind a TLS-intercepting proxy): `NODE_OPTIONS=--use-system-ca npm install`.
- **Validate the plugin** (from repo root): `claude plugin validate ./local-cc-plugin --strict`.

**Critical rebuild rule:** `mcp/server.bundle.mjs` is committed and inlines `mcp/server.ts`,
`mcp/handlers.ts`, `scripts/db.ts`, and `scripts/gitctx.ts`. After editing any of those, run
`npm run build` and commit the regenerated bundle — CI fails if it drifts (`git diff --exit-code mcp/server.bundle.mjs`).

## Architecture (where things live)
The repo root holds only marketplace + docs; the entire plugin is in **`local-cc-plugin/`**
(the plugin was renamed from `session-journal`; that name now denotes the MCP server inside it).
Two runtimes share **one SQLite store** at `${CLAUDE_PLUGIN_DATA}/state.db`:
- **Hook scripts** (`scripts/*.ts`, wired in `hooks/hooks.json`) run via `node --experimental-strip-types`
  with **zero `node_modules`** — they use built-in `node:sqlite`. Cover SessionStart (journal + auto-recall),
  PreToolUse/Bash (guardrail), PostToolUse (edit logging), SessionEnd, PreCompact, Stop (hygiene gate).
- **MCP server** (`mcp/server.ts` → bundled `server.bundle.mjs`, launched by `.mcp.json`) exposes the
  `store` / `recall` / `forget` / `pin` / `journal` tools. Registration shell only — behavior is in `handlers.ts`.
- **`scripts/db.ts`** is the shared schema + migration layer imported by both runtimes (hence the rebuild rule).
- **Pure logic is extracted for unit testing**, each with a sibling `.test.ts`: `guardrail-policy.ts`,
  `gitctx.ts` (repo scoping), `rollup.ts`, `checks.ts`, `mcp/handlers.ts`. Keep new logic in this pure-function
  shape rather than inline in hooks/server so it stays testable without spawning the bundle.

## What we're building
A single Claude Code **plugin bundle** containing all four primitives: slash command(s),
a subagent, hooks, and an MCP server. Distributed local-first, shareable later via marketplace.

**v1 (core):** session journal + cross-session memory + guardrails.
- Journal: log every file edit and session boundary to a SQLite store.
- Memory/recall: an MCP server exposing `store` and `recall` tools backed by the same DB.
- Guardrails: a PreToolUse hook that blocks risky Bash commands.
- A slash command and a subagent that read/write the store.

**v2 (later phase, do NOT start until v1 passes end-to-end):** dev-hygiene gating
(lint/format/test) layered on the same store. Leave hooks for this stubbed/commented in v1.

## Stack decision (locked)
- **TypeScript/Node** for the MCP server and hook scripts.
- Run hook scripts via `node --experimental-strip-types` (no build step). **Requires Node >= 22.6.0** — verify with `node --version` before relying on it.
- Persist `node_modules` in `${CLAUDE_PLUGIN_DATA}` using the SessionStart install pattern (see below).
- SQLite for the store. Prefer `node:sqlite` if the runtime supports it; otherwise `better-sqlite3` installed into `${CLAUDE_PLUGIN_DATA}`.

## v1 implementation notes (what actually shipped — supersedes parts of "Stack decision")
Deliberate, validated deviations from the locked stack:
- **MCP delivery: bundled, NOT runtime-installed.** The server is bundled with esbuild into a
  single committed `mcp/server.bundle.mjs` (SDK stdio path + zod inlined; express/hono
  tree-shaken). `.mcp.json` runs it with zero `node_modules`; there is no SessionStart install
  hook. Rationale: this machine sits behind TLS interception (a corporate root CA Node doesn't
  trust by default), so runtime `npm install` failed/hung — `UNABLE_TO_VERIFY_LEAF_SIGNATURE`,
  surfacing as npm's misleading "Exit handler never called!". Bundling means end users never run
  npm (they'd hit the same wall behind their own proxies). The persistent-`node_modules` pattern
  is therefore unused in v1.
- **A build step exists for the MCP server only:** `npm run build` (esbuild) regenerates the
  bundle. Hook scripts still run via `node --experimental-strip-types` with no build, as specified.
- **Dev install behind a TLS proxy:** `NODE_OPTIONS=--use-system-ca npm install` (trusts the OS
  cert store).
- **Journaling hooks use only `node:sqlite`** (built-in), so they need no `node_modules` and work
  independent of the bundle.
- **Guardrail "writes outside project dir" rule deferred** (static parsing too false-positive-prone);
  `rm -rf` of dangerous targets, pipe-to-shell, and force-push-to-protected-branch are enforced.

## v2 implementation notes (dev-hygiene gating — shipped)
- **Opt-in by design:** the Stop hook runs nothing unless `format_command` / `lint_command` /
  `test_command` are set in `userConfig` (exported to the hook as `CLAUDE_PLUGIN_OPTION_*`).
  Zero impact by default.
- **Gate = Stop hook, `exit 2` on failure**, gated on `stop_hook_active` (fires once per
  turn-chain to avoid a stop/continue deadlock). Each run logged to the `checks` table.
- **Check commands run via `execSync` (platform default shell):** `cmd.exe` on Windows,
  `/bin/sh` on POSIX. Keep configured commands shell-agnostic (e.g. `npm test`); avoid `;`/`&&`
  chains that parse differently across shells. The unit tests use `node -e` for exactly this reason.
- `/hygiene` runs the same commands on demand via `${user_config.*}` substitution in the command body.
- Adding the `checks` table to `db.ts` changed the MCP bundle (db.ts is inlined) → rebuilt;
  CI's bundle-in-sync check enforces it.

## v3 implementation notes (git-aware memory — shipped)
- **Auto-recall (closes the store→recall loop):** a 2nd SessionStart hook
  (`hook-session-start-recall.ts`) resolves the repo via `gitctx` and prints this repo's recent
  notes to stdout, which SessionStart injects into context. Best-effort, bounded (~10 notes / 2 KB),
  never blocks.
- **Repo scoping:** `notes`/`sessions` are tagged with repo (+ branch/commit). The MCP server derives
  the repo from `CLAUDE_PROJECT_DIR` (added to `.mcp.json` env); `store` tags `notes.repo`, `recall`
  defaults to `repo = current OR repo IS NULL` with `scope:'all'` to override. Repo id = normalized
  remote URL (`owner/name`), falling back to the git toplevel dir name.
- **First real migration:** `db.ts` `addColumnIfMissing` (via `PRAGMA table_info`) adds the new columns
  to pre-v3 DBs (verified PRAGMA works through `node:sqlite` `prepare().all()`).
- **Dynamic default branch:** `evaluate(command, protectedBranches)` stays pure; the guardrail hook
  computes the repo's real default via `gitctx.defaultBranch()` (∪ main/master fallback) and passes it in.
- `gitctx.ts` is inlined into the bundle (imported by `server.ts`) → rebuild required. Its pure
  `normalizeRepo`/`parseDefaultBranchRef` are unit-tested; git calls are best-effort (never throw).

## v4 implementation notes (guardrail hardening + journal tool — shipped)
- **Guardrail additions** (pure, in `guardrail-policy.ts`): fork bombs (self-piping function via a
  backreference), `dd of=/dev/<disk>`, `mkfs* /dev/*`, recursive `chmod 777` on a catastrophic target.
  The dangerous-target check was generalized to `hasDangerousTargetAfter(command, name)` (skips octal
  modes so chmod reuses it). 33 unit cases.
- **`journal` MCP tool:** lists recent `edits` JOINed to `sessions` filtered by the current repo
  (strict `s.repo = current` — no cross-repo leakage of file paths). Bundle rebuild.
- Still deferred: guardrail "writes outside the project dir" (too false-positive-prone for static parsing).

## v5 implementation notes (clarify-intent requirement gathering — shipped)
- **Plugin's first `skill`:** `skills/clarify-intent/SKILL.md` holds the methodology; `skills/` is a
  plugin-root component dir, auto-discovered (no `plugin.json` change, no bundle rebuild — markdown only).
- **Stakeholder-interview flow:** `/clarify-intent` (thin entry) runs the skill, which asks a mix of
  multiple-choice (`AskUserQuestion`) and open-ended questions across six requirement dimensions,
  composes a doc, then calls the `requirements-verifier` subagent.
- **Fast verify:** `requirements-verifier` runs on `model: haiku`, **no tools**, single pass — the doc
  is passed **inline** in the invocation prompt (no `recall` round-trip). Fixed 6-dim rubric →
  READY/NOT-READY + coverage checklist + blocking gaps. Skill loops on gaps, capped at 2 rounds.
- **Persist:** final doc saved via `mcp__session-journal__store` (`key: requirements`). Isolated in a
  marked PERSIST BLOCK in the skill so it can be repointed at a dedicated store later.

## v6 implementation notes (umbrella rename + `/init` view setup — shipped)
- **Plugin renamed `session-journal` → `local-cc-plugin`** (umbrella name; placeholder). The
  rename is cheap because **the MCP server keeps the name `session-journal`** (the server key in
  `.mcp.json`): every `mcp__session-journal__*` tool id is unchanged and the bundle is byte-identical,
  so **no rebuild**. Changed: dir (`git mv`), `plugin.json`/`package.json`/`package-lock.json` names,
  `marketplace.json` entry + `source`, CI `working-directory` + `validate` path, and dir/path mentions
  in docs. *Kept* `session-journal`: server registration, tool ids, hook log prefixes, user-facing
  "session-journal memory" handoff text, test temp-dir names.
- **State-dir migration:** `${CLAUDE_PLUGIN_DATA}` = `~/.claude/plugins/data/{plugin-name}-{marketplace-name}/`,
  so renaming the plugin orphans the old store. Migrated by `cp -R` of the old data dir
  (`session-journal-cc-plugins`) to the new id (`local-cc-plugin-cc-plugins`) once.
- **`/init` command:** interactive (`AskUserQuestion`) setup that writes `viewMode` + `outputStyle`
  into the user's `settings.json`. Plugins **cannot** natively inject harness settings, so this is a
  user-run command, backed by `scripts/apply-view-prefs.ts` (pure `applyPrefs` + a thin CLI; uses only
  `node:fs`/`os`/`path`, **not** in the MCP bundle). Non-destructive (preserves existing keys),
  idempotent, bails on malformed settings JSON.

## Verified mechanics (confirmed against code.claude.com/docs/en/plugins-reference — trust these)
- **Layout:** ONLY `plugin.json` goes in `.claude-plugin/`. Every component dir (`commands/`,
  `agents/`, `hooks/`, `skills/`, `.mcp.json`) lives at the **plugin root**.
- **Manifest:** only `name` is required (kebab-case). `version` optional: if set, you must bump
  it for users to get updates; if omitted, git SHA is the version (every commit = update).
- **State dir `${CLAUDE_PLUGIN_DATA}`** → `~/.claude/plugins/data/{id}/`. Survives updates &
  reinstalls. **This is the only correct place to write persistent state.**
- **`${CLAUDE_PLUGIN_ROOT}` is EPHEMERAL** — wiped ~7 days after an update. Never write state here;
  read-only (scripts, bundled config). Always quote: `"${CLAUDE_PLUGIN_ROOT}"`.
- **Secrets:** declare in `userConfig` with `"sensitive": true`. Stored in system keychain
  (~2KB total limit) or `~/.claude/.credentials.json` fallback. Substitute as
  `${user_config.KEY}` in `.mcp.json`/hooks; exported to subprocesses as `CLAUDE_PLUGIN_OPTION_<KEY>`.
  NEVER commit a secret to any plugin file.
- **Plugin-shipped agents** may NOT declare `hooks`, `mcpServers`, or `permissionMode` in
  frontmatter (load-time security rejection). Declare hooks at plugin level in `hooks/hooks.json`.
- **Hook handler types:** `command`, `http`, `mcp_tool`, `prompt`, `agent`.
- **Hook events we use:** `SessionStart`, `PreToolUse`, `PostToolUse`, `SessionEnd`, `Stop`.
  Event names are case-sensitive.
- **Composition:** hooks can call MCP tools / spawn agents; a slash command/skill can instruct
  Claude to use a named subagent or `mcp__server__tool`. Subagents CANNOT spawn subagents.
  MCP servers CANNOT fire hooks.
- **Use `command` hooks for hard policy** (e.g. the guardrail). `mcp_tool` hooks are
  non-blocking if the MCP server is down — fine for journaling/enrichment, NOT for security.

## Hook safety rules (non-negotiable)
- Hard block = **`exit 2`** (NOT `exit 1`, which is non-blocking).
- `Stop` hooks: gate on `stop_hook_active` to avoid infinite loops:
  `[ "$(echo "$INPUT" | jq -r '.stop_hook_active')" = "true" ] && exit 0`
- Set an explicit `"timeout"` (5–30s) on every hook; mark non-critical ones `"async": true`.
- `chmod +x` every script; shebang `#!/usr/bin/env bash` (or run node directly).
- Exact matcher case: `Write|Edit|MultiEdit`, `Bash`.

## VERIFY — do NOT trust blind (flagged uncertain)
These came from prior research and are NOT confirmed against primary sources. Test empirically; do not design around them until reproduced:
- Claim: `--plugin-dir` doesn't load inline `mcpServers` (alleged issue #15308) → **just test it.**
  If MCP doesn't appear under `/mcp` in local dev, try also passing `--mcp-config ./<plugin>/.mcp.json`.
- Claim: inline `mcpServers` in plugin.json gets dropped (alleged #16143) → docs show inline as
  supported. We use a **separate `.mcp.json`** anyway (cleaner), so this is moot.
- Claim: disabled plugins still run hooks (#39307); userConfig prompt sometimes doesn't fire
  (#39455/#39827) → treat as rumors; verify if you hit odd behavior.
- All version floors (e.g. `bin/` @ 2.1.91, displayName @ 2.1.143) — confirm against
  `claude --version` + live docs before depending on them.

## Persistent node_modules pattern (from docs, confirmed)
SessionStart hook that (re)installs deps only when package.json changes:
diff the bundled `package.json` against the copy in `${CLAUDE_PLUGIN_DATA}`; on mismatch,
copy it over and `npm install` there; on failure `rm` the copy so next session retries.
MCP server then runs with `NODE_PATH=${CLAUDE_PLUGIN_DATA}/node_modules`.

## Data model (SQLite @ ${CLAUDE_PLUGIN_DATA}/state.db)
- `sessions(id, started_at, ended_at, cwd)`
- `edits(id, session_id, tool, file_path, ts)`
- `notes(id, session_id, key, body, ts)`  ← memory/recall store
Keep it minimal; migrations can come later.

## Guardrail default blocklist (conservative; tune later)
Block (exit 2) on Bash commands matching: `rm -rf` on `/` or `~` or `..`; `git push --force`
to a protected branch; pipe-to-shell (`curl … | sh`, `wget … | bash`); writes outside the
project dir. When in doubt, `ask` rather than `deny`. Log every decision to the journal.

## Build order (each step has an acceptance gate — see kickoff prompt)
0 prereqs → 1 scaffold+manifest → 2 SQLite lib → 3 MCP store/recall tools →
4 journal hooks (SessionStart/PostToolUse/SessionEnd) → 5 guardrail PreToolUse hook →
6 slash command + subagent using the store → 7 local end-to-end verify →
8 marketplace.json (still local) → 9 GitHub publish → 10 (v2) dev-hygiene gating.

## Definition of done (v1)
`claude plugin validate ./<plugin> --strict` exits 0; in a session `/plugin`, `/agents`,
`/mcp` all show the plugin's components; a file edit creates an `edits` row; a risky Bash
command is blocked; `recall` returns previously stored notes across a session restart.
