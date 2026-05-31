---
description: Report how full the current context window is and suggest when to checkpoint/compact.
allowed-tools: mcp__session-journal__context_budget
---

The user wants to know how much of the context window is in use right now.

1. Call `mcp__session-journal__context_budget` (no arguments unless the user named a specific
   context-window size, in which case pass it as `window_tokens`).
2. Relay the report in one line, then the suggested action verbatim. If it reports it couldn't read
   the transcript, say so plainly and don't guess a number.
3. If occupancy is in the warn/high range, offer to run `/checkpoint` (saves a handoff) followed by
   `/compact` — the PreCompact hook also writes a `compact-handoff` automatically, so compacting is
   safe.

Arguments: $ARGUMENTS
