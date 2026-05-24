# cc-plugins

A [Claude Code](https://claude.com/claude-code) plugin marketplace.

## Plugins

| Plugin | What it does |
| :----- | :----------- |
| [`session-journal`](./session-journal) | Session journal, cross-session memory (`store`/`recall`), Bash guardrails, and opt-in dev-hygiene gating. |

## Install

```text
/plugin marketplace add cdblake1/cc-plugins
/plugin install session-journal@cc-plugins
```

---

## session-journal

Four capabilities, one small SQLite store (at `${CLAUDE_PLUGIN_DATA}/state.db`, which
survives plugin updates and reinstalls):

- **Journal** — hooks record every file edit and session boundary.
  - `SessionStart` / `SessionEnd` write `sessions` rows; `PostToolUse` (Write/Edit/MultiEdit)
    writes `edits` rows.
- **Memory** — an MCP server exposing two tools backed by the same store:
  - `mcp__session-journal__store` — persist a note (optional `key`).
  - `mcp__session-journal__recall` — fetch notes, filter by `key` / `query`.
- **Guardrails** — a `PreToolUse` (Bash) hook that **hard-blocks** dangerous commands
  (`rm -rf` of `/`·`~`·`$HOME`·`..`, piping a download into a shell, force-pushing to
  `main`/`master`), asks on softer risks (other force-pushes, `sudo`), and logs every
  decision.
- **Dev-hygiene gating** (opt-in) — a `Stop` hook runs your configured `format`/`lint`/`test`
  commands when Claude finishes; if any fail, the turn is **blocked** until they pass. Results
  are logged to a `checks` table. Off by default (runs nothing until you configure a command).

### Components

- Slash command **`/journal [note or query]`** — store a note and/or recall recent ones.
- Slash command **`/hygiene`** — run your configured dev-hygiene checks on demand.
- Subagent **`journal-keeper`** — remembers and recalls cross-session context.
- MCP server **`session-journal`** — the `store` / `recall` tools above.

### Configuration (dev-hygiene gating)

Set any of these in the plugin's configuration (prompted at enable time, or via
`/plugin`). All are optional — an empty command disables that check:

| Option | Example | Effect |
| :----- | :------ | :----- |
| `format_command` | `npm run format` | Run at `Stop`; non-zero blocks the turn |
| `lint_command` | `npm run lint` | Run at `Stop`; non-zero blocks the turn |
| `test_command` | `npm test` | Run at `Stop`; non-zero blocks the turn |

The gate fires once per turn-chain (gated on `stop_hook_active`), giving Claude one shot to
fix failures before the turn can end. Keep the commands reasonably fast.

### Requirements

- **Node ≥ 22.6.0** on `PATH` (hook scripts run via `node --experimental-strip-types`;
  the store uses the built-in `node:sqlite`).

### Building (contributors)

The MCP server ships as a committed, self-contained bundle
(`session-journal/mcp/server.bundle.mjs`) so it runs with **zero runtime dependencies** —
no `npm install` on the user's machine. Rebuild it after editing `mcp/server.ts`,
`scripts/db.ts`, or bumping a dev dependency:

```bash
cd session-journal
npm install      # behind a TLS-intercepting proxy: NODE_OPTIONS=--use-system-ca npm install
npm run build    # regenerates mcp/server.bundle.mjs via esbuild
npm test         # guardrail + check-runner unit tests
```

CI rebuilds the bundle and fails on any drift (`git diff --exit-code`), runs the tests, and
validates the manifest — so the committed bundle is always in sync with source.

## License

[MIT](./LICENSE)
