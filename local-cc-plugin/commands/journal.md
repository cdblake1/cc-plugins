---
description: Recall recent journal notes; optionally store, pin, or forget from the arguments.
argument-hint: "[note to remember, or a search query, or 'pin #N' / 'forget #N']"
allowed-tools: mcp__session-journal__store, mcp__session-journal__recall, mcp__session-journal__forget, mcp__session-journal__pin
---

You manage the **session-journal** cross-session memory store through its MCP tools.

Do the following:

1. Inspect the arguments below:
   - If they look like **`pin #<id>`** / **`unpin #<id>`**, call `mcp__session-journal__pin`
     with that id (and `pinned:false` for unpin).
   - If they look like **`forget #<id>`**, call `mcp__session-journal__forget` with that id.
   - If they look like a **search query**, pass them as `query` to `recall` (FTS5).
   - Otherwise, treat them as a fact to **store** via `mcp__session-journal__store` (pick
     a short lowercase `key` if the note clearly belongs to a recurring topic).
2. Then call `mcp__session-journal__recall` to fetch recent notes (default scope).
3. Present the recalled notes concisely, newest first, as a short bulleted list (include
   each note's key and any tags when set, and mark pinned ones). If there are none, say so.

Arguments: $ARGUMENTS
