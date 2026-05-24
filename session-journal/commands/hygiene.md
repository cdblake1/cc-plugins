---
description: Run the configured dev-hygiene checks (format/lint/test) now and report pass/fail.
allowed-tools: Bash
---

Run this project's configured dev-hygiene checks on demand (the same commands the Stop gate
uses) and report a concise pass/fail summary for each. Skip any that are empty.

- Format: `${user_config.format_command}`
- Lint: `${user_config.lint_command}`
- Test: `${user_config.test_command}`

For each non-empty command above, run it with the Bash tool, then summarize: ✓/✗ per check
with a short reason on failure. If all three are empty, tell the user no dev-hygiene commands
are configured and that they can set them via the plugin's configuration (format_command /
lint_command / test_command).
