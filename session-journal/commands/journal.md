---
description: Recall recent journal notes; optionally store a new note from the arguments.
argument-hint: "[note to remember, or a search query]"
allowed-tools: mcp__session-journal__store, mcp__session-journal__recall
---

You manage the **session-journal** cross-session memory store through its MCP tools.

Do the following:

1. If arguments are provided below, store them as a note by calling
   `mcp__session-journal__store` with `body` set to the argument text. Pick a short,
   lowercase `key` if the note clearly belongs to a recurring topic.
2. Then call `mcp__session-journal__recall` to fetch recent notes. If the arguments look
   like a search rather than a fact to save, pass them as the `query` instead of storing.
3. Present the recalled notes concisely, newest first, as a short bulleted list (include
   each note's key when set). If there are none, say so plainly.

Arguments: $ARGUMENTS
