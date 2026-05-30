---
description: Gather requirements stakeholder-style (multiple-choice + open-ended), then verify they're complete enough to build.
argument-hint: "[what you want to build]"
allowed-tools: mcp__session-journal__store
---

Run the **clarify-intent** skill: act as the engineering team interviewing the user (the
stakeholder) to understand intent **before** building. Ask a mix of multiple-choice
(`AskUserQuestion`) and open-ended questions across the six requirement dimensions, compose a
structured requirements doc, then hand it to the `requirements-verifier` subagent to judge whether
enough has been gathered. Loop on gaps (max 2 rounds), then save the result and present the verdict.

Treat the arguments below as the thing to build; fold them into the opening framing step.

Arguments: $ARGUMENTS
