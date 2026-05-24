---
description: Summarize the current session and save it as a checkpoint for next time.
argument-hint: "[optional extra context to fold in]"
allowed-tools: mcp__session-journal__store, mcp__session-journal__journal
---

Write a concise **checkpoint** of the current session so a future session (which starts with no
memory of this one) can pick up where you left off — then save it to cross-session memory.

Do the following:

1. If you need a reminder of what changed, call `mcp__session-journal__journal` to see this
   session's recent file edits.
2. Compose a tight, structured summary. Include only the sections that apply:
   - **Goal** — what we're trying to accomplish overall.
   - **Done** — what was completed this session.
   - **Open** — work in progress or unresolved threads.
   - **Next** — the concrete next step(s) to take.
   - **Watch** — decisions, gotchas, or constraints worth remembering (use absolute dates, not
     "today"/"yesterday", since this will be read in a future session).
   A few lines per section — a handoff note, not a transcript.
3. Save it: call `mcp__session-journal__store` with `key` set to `checkpoint` and `body` set to
   the summary. (The `SessionStart` auto-recall hook surfaces the most recent `checkpoint` first,
   so this is what the next session sees on open.)
4. Show the saved checkpoint to the user and confirm it was stored.

If extra context is provided below, fold it into the checkpoint.

Arguments: $ARGUMENTS
