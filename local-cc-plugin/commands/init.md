---
description: Set Claude Code's view verbosity (viewMode + outputStyle) in your user settings — interactively, non-destructively.
allowed-tools: Read, Bash, AskUserQuestion
---

Help the user reduce (or change) Claude Code's display verbosity by setting `viewMode` and
`outputStyle` in their **user** `settings.json`. Be non-destructive and explicit.

Do the following:

1. **Show current state.** Read the user settings file with the `Read` tool:
   `${CLAUDE_CONFIG_DIR}/settings.json` if `CLAUDE_CONFIG_DIR` is set, otherwise
   `~/.claude/settings.json`. If it doesn't exist, say so (a fresh file will be created). Report
   the current `viewMode` and `outputStyle` values (or "unset").

2. **Ask what they want** using `AskUserQuestion` — two questions:
   - **View mode** (`viewMode`): `focus` — condensed: one-line tool summaries + diffstats, hides
     full diffs/output (recommended for less noise) · `default` — standard transcript · `verbose`
     — full tool results.
   - **Output style** (`outputStyle`): `Concise` — shorter prose (recommended) · `Default` —
     standard · *Leave unchanged* — don't touch outputStyle.

3. **Apply** by running the helper script with the chosen values (omit a flag for any "leave
   unchanged" answer):
   ```bash
   node --experimental-strip-types --no-warnings \
     "${CLAUDE_PLUGIN_ROOT}/scripts/apply-view-prefs.ts" \
     --view-mode <choice> --output-style <choice>
   ```
   The script preserves all other settings, is idempotent, and refuses to write if the existing
   `settings.json` is malformed. Relay its output.

4. **Report** what changed and note the effect:
   - `viewMode` takes effect immediately for new output; you can also toggle it live with `/focus`.
   - `outputStyle` applies after `/clear` or a restart (it's read at session start).

If the user passed arguments below, treat them as a hint for the defaults (e.g. "focus", "quiet",
"verbose") but still confirm via the questions unless they clearly asked to skip prompts.

Arguments: $ARGUMENTS
