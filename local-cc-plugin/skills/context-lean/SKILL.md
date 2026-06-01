---
name: context-lean
description: >-
  Practices for keeping the main conversation's context/token usage lean on long or exploratory
  tasks. Use when a session is getting long, context feels heavy, /context-budget (or the budget
  nudge) reports high occupancy, you're about to read many or large files, or the user asks to keep
  context/tokens down or work efficiently across a big task. Complements the plugin's PreCompact
  handoff (compaction is safe) and context_budget tool (occupancy is visible).
---

You are keeping the **main thread** lean — minimizing what occupies the context window so long tasks
stay coherent and cheap. The plugin already makes compaction *safe* (the PreCompact hook auto-saves a
`compact-handoff`) and *visible* (`/context-budget` + the optional UserPromptSubmit nudge). This skill
is the discipline for *acting* on that. Apply the practices below; prefer the cheapest that fits.

## 1. Delegate fan-out reads to subagents
When a step means scanning many files or surveying an unfamiliar area, run it in a subagent (the Task
/ Explore tools) instead of reading everything yourself. The subagent's large intermediate context
(file dumps, dead-end reads) stays out of the main thread — only its conclusion returns.
- Good fits: "where is X handled across the codebase", "summarize how this subsystem works", broad
  grep-and-read sweeps, multi-file audits.
- Give the subagent a specific question and ask for just the answer (paths + the conclusion), not the
  raw excerpts.

## 2. Recall before re-reading
Check cross-session memory and the activity journal before re-opening files you (or a past session)
already summarized: `mcp__session-journal__recall` for notes/decisions, `mcp__session-journal__journal`
for what was edited. A one-line recalled note is far cheaper than re-reading the file it describes.

## 3. Read large files in slices, once
- Use `offset`/`limit` to read only the region you need rather than whole large files.
- Don't re-read a file you just edited — the edit already reflects its current state.
- Search (Grep) to locate the relevant lines first, then read a tight window around them.

## 4. Checkpoint + compact at milestones
When `/context-budget` (or the nudge) shows occupancy in the warn/high range **and** a unit of work is
done, capture and shed:
1. `/checkpoint` — saves a deliberate handoff note.
2. `/compact` (or `/clear` for a hard reset) — the PreCompact hook also auto-writes a
   `compact-handoff`, so nothing in flight is lost; next session's SessionStart resurfaces it.
Do this at natural seams (a feature landed, a phase done), not mid-edit.

## 5. Keep what you emit tight
- Don't paste large tool outputs or file contents back into the conversation to "show work" — refer to
  `path:line` instead; it's clickable and cheap.
- Summarize long command output rather than echoing it wholesale.

## When NOT to bother
Short, focused tasks with a known set of files don't need any of this — reading the two files you need
directly is leaner than spinning up a subagent. Reach for these practices when breadth or session
length is the cost, not for every task.
