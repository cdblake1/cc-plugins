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

## Future / backlog
- [ ] Auto-detect dev-hygiene commands from `package.json` scripts when userConfig is unset
- [ ] Format-on-edit (PostToolUse) — advisory or auto-fix
- [ ] Guardrail tuning: fork bombs, `dd`/`mkfs` to devices, `chmod -R 777 /`, writes outside project dir
- [ ] Expose the journal (`edits`/`sessions`) via an MCP tool or command
