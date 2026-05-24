# PLAN — cc-plugins / session-journal

Roadmap as a checklist. See `CHANGELOG.md` for shipped history and `CLAUDE.md` for the build spec.

## v1 — core (shipped, PR #1)
- [x] Scaffold + manifest (`claude plugin validate --strict`)
- [x] SQLite store (`node:sqlite`): `sessions` / `edits` / `notes`
- [x] MCP server `store` / `recall` — shipped as a committed esbuild bundle (zero runtime deps)
- [x] Journal hooks: SessionStart/SessionEnd → `sessions`; PostToolUse Write|Edit|MultiEdit → `edits`
- [x] Guardrail PreToolUse(Bash): block `rm -rf` danger / pipe-to-shell / force-push to main|master; ask on softer; log
- [x] `/journal` command + `journal-keeper` subagent
- [x] Local marketplace + GitHub publish

## Repo health (shipped, PR #2)
- [x] CI: bundle-in-sync diff + guardrail tests + `validate --strict`
- [x] Pure `guardrail-policy.ts` + committed tests (18 cases)
- [x] `.gitattributes` (LF) + deterministic bundle (`absWorkingDir`)

## v2 — dev-hygiene gating (shipped, PR #3)
Opt-in: does nothing until the user configures a command, so no slowdown by default.
- [x] `userConfig`: `format_command`, `lint_command`, `test_command` (optional strings)
- [x] `checks` table in the store: `(id, session_id, kind, command, ok, output, ts)`
- [x] Stop hook: run configured lint/test; **block (exit 2)** on failure; gate on `stop_hook_active`; log to `checks`
- [x] `/hygiene` command: run configured checks on demand
- [x] Tests for the check-runner logic (`checks.test.ts`)
- [x] Rebuild bundle (db.ts schema changed) + CI green
- [x] Bump plugin version 0.1.0 → 0.2.0
- [x] Docs: README (userConfig + gating), CLAUDE.md (v2 notes), CHANGELOG

## v3 — git-aware memory (shipped, PR #4, v0.3.0)
- [x] `gitctx.ts` — `gitContext` / `defaultBranch` / pure `normalizeRepo` (bundled + used by hooks)
- [x] Schema + first migration: `repo`/`branch`/`commit_sha` on `sessions`, `repo` on `notes` (`addColumnIfMissing`)
- [x] **Auto-recall** SessionStart hook injects this repo's recent notes into context
- [x] Repo-scoped `store`/`recall` (server reads `CLAUDE_PROJECT_DIR`); `recall` gains `scope: repo|all`
- [x] Guardrail uses the repo's dynamic default branch (∪ main/master)
- [x] Tests: `gitctx.test.ts` + custom-branch guardrail cases; bundle rebuilt; CI green

## v4 — hardening + journal read (shipped, PR #5, v0.4.0)
- [x] Guardrail: fork bombs, `dd`/`mkfs` to block devices, recursive `chmod 777` on system paths (33 test cases)
- [x] `journal` MCP tool — recent edits for the current repo (repo-scoped JOIN)

## v5 — auto-capture + handoff (shipped, v0.5.0)
Closes the capture gap: the store no longer depends on someone remembering to write a note.
Feasibility-verified first (model-invoking `agent` hooks are REPL-only; `command` hooks run in
headless `-p` and `SessionEnd` blocks on them → use a deterministic `command`-hook rollup).
- [x] `/checkpoint` command — model writes a Goal/Done/Open/Next/Watch handoff, stored under key `checkpoint`
- [x] Deterministic `SessionEnd` rollup note (key `session-rollup`) from journal data; opt out via `auto_rollup = "off"`
- [x] Handoff at `SessionStart`: auto-recall leads with the latest checkpoint/rollup, then earlier notes
- [x] Pure `rollup.ts` + unit tests; no schema/bundle change (reuses `store` + `notes`)

## Future / backlog
- [ ] **Tier 2 — per-prompt recall** (`UserPromptSubmit` hook + SQLite FTS5 ranking) for targeted surfacing
- [ ] **Tier 1 (opt-in) — model narrative rollup**: `SessionEnd` `command` hook shells to `claude -p`
      for a written summary (needs a re-entrancy guard; nested `-p` re-fires hooks)
- [ ] **Tier 3 — note lifecycle**: `expires_at` / `superseded_by` / done-marking; recall filters stale
- [ ] Auto-detect dev-hygiene commands from `package.json` scripts when userConfig is unset
- [ ] Format-on-edit (PostToolUse) — advisory or auto-fix
- [ ] Guardrail: "writes outside the project dir" rule (deferred — static parsing too false-positive-prone)
