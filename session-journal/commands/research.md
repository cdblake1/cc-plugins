---
description: Cost-aware research — auto-picks a tier (light/medium/heavy) + route (web/codebase), confirms cost, then runs and saves the report.
argument-hint: "[the question to research]"
allowed-tools: mcp__session-journal__store
---

Run the **research** skill. Read the question below, judge the right **route** (web vs codebase)
and **complexity tier** (light / medium / heavy) using the criteria in the skill, confirm the
proposed tier + rough cost with the user via `AskUserQuestion` **before spending**, then run the
research with the matching machinery, return the report inline, and persist it to the journal store.

Keep raw sources out of the main context (delegate to a subagent) and never run the heavy tier
silently.

Arguments: $ARGUMENTS
