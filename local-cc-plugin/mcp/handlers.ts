// Pure(-ish) MCP tool handlers for session-journal. Each function takes an open
// DatabaseSync handle plus its inputs and returns the text payload the MCP server
// wraps as `{ content: [{ type: "text", text }] }`. Extracted from server.ts so the
// handlers can be unit-tested against in-memory DBs without spawning the bundle —
// mirrors the guardrail-policy.ts / rollup.ts pattern already used in this repo.

import type { DatabaseSync } from "node:sqlite";
import { now } from "../scripts/db.ts";
import { formatBudget, liveContextTokens, type ContextUsage } from "../scripts/transcript.ts";

export type StoreInput = { body: string; key?: string; tags?: string[] };
export type RecallInput = {
  key?: string;
  tags?: string[];
  query?: string;
  since?: string;
  until?: string;
  scope?: "repo" | "all";
  limit?: number;
};
export type ForgetInput = { id?: number; key?: string; confirm?: "yes" };
export type PinInput = { id: number; pinned?: boolean };
export type JournalInput = { limit?: number };
export type ContextBudgetInput = { window_tokens?: number };

type NoteRow = {
  id: number;
  repo: string | null;
  key: string | null;
  body: string;
  ts: string;
  pinned?: number;
};

/** Lowercase, trim, drop empties, dedupe. Caller passes raw user input. */
export function normalizeTags(tags: string[] | undefined): string[] {
  if (!tags?.length) return [];
  const seen = new Set<string>();
  for (const raw of tags) {
    const t = String(raw).trim().toLowerCase();
    if (t.length > 0) seen.add(t);
  }
  return [...seen];
}

/**
 * Sanitize a user query for FTS5 MATCH. FTS5 treats `"`, `*`, `(`, `)`, `:`, `^`, `-`, `+`
 * as operators; the safest "just find this text" default is a wrapped phrase match.
 * Embedded `"` are doubled (FTS5's escape inside a quoted phrase).
 */
export function ftsPhrase(query: string): string {
  return `"${query.replace(/"/g, '""')}"`;
}

export function handleStore(
  db: DatabaseSync,
  input: StoreInput,
  currentRepo: string | null,
): string {
  const tags = normalizeTags(input.tags);
  const info = db
    .prepare("INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)")
    .run(null, currentRepo, input.key ?? null, input.body, now());
  const noteId = Number(info.lastInsertRowid);
  if (tags.length > 0) {
    const ins = db.prepare("INSERT OR IGNORE INTO note_tags(note_id, tag) VALUES (?, ?)");
    for (const t of tags) ins.run(noteId, t);
  }
  const scopeNote = currentRepo ? ` for ${currentRepo}` : "";
  const keyNote = input.key ? ` under key "${input.key}"` : "";
  const tagNote = tags.length ? ` with tags [${tags.join(", ")}]` : "";
  return `Stored note #${noteId}${keyNote}${tagNote}${scopeNote}.`;
}

export function handleRecall(
  db: DatabaseSync,
  input: RecallInput,
  currentRepo: string | null,
): string {
  const clauses: string[] = [];
  const params: (string | number)[] = [];

  // Repo scoping (default). Skipped when scope='all' or when we can't tell the repo.
  if (input.scope !== "all" && currentRepo) {
    clauses.push("(n.repo = ? OR n.repo IS NULL)");
    params.push(currentRepo);
  }
  if (input.key) {
    clauses.push("n.key = ?");
    params.push(input.key);
  }
  if (input.since) {
    clauses.push("n.ts >= ?");
    params.push(input.since);
  }
  if (input.until) {
    clauses.push("n.ts <= ?");
    params.push(input.until);
  }
  const tags = normalizeTags(input.tags);
  if (tags.length > 0) {
    const placeholders = tags.map(() => "?").join(", ");
    clauses.push(`n.id IN (SELECT note_id FROM note_tags WHERE tag IN (${placeholders}))`);
    params.push(...tags);
  }

  const limit = input.limit ?? 20;
  let sql: string;
  if (input.query) {
    // FTS5 path: join through notes_fts, MATCH the wrapped phrase.
    clauses.push("f.notes_fts MATCH ?");
    params.push(ftsPhrase(input.query));
    const where = `WHERE ${clauses.join(" AND ")}`;
    sql =
      `SELECT n.id, n.repo, n.key, n.body, n.ts, n.pinned ` +
      `FROM notes_fts f JOIN notes n ON n.id = f.rowid ${where} ORDER BY n.id DESC LIMIT ?`;
  } else {
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    sql = `SELECT n.id, n.repo, n.key, n.body, n.ts, n.pinned FROM notes n ${where} ORDER BY n.id DESC LIMIT ?`;
  }

  const rows = db.prepare(sql).all(...params, limit) as NoteRow[];
  if (rows.length === 0) return "No matching notes.";

  // Batch-fetch tags for the returned ids so we can show them inline.
  const tagMap = fetchTagsFor(
    db,
    rows.map((r) => r.id),
  );
  return rows
    .map((r) => {
      const pin = r.pinned ? " 📌" : "";
      const keyPart = r.key ? ` (${r.key})` : "";
      const tagPart = tagMap.get(r.id)?.length ? ` [${tagMap.get(r.id)!.join(", ")}]` : "";
      return `#${r.id}${pin} [${r.ts}]${keyPart}${tagPart}: ${r.body}`;
    })
    .join("\n");
}

export function handleForget(db: DatabaseSync, input: ForgetInput): string {
  if (input.id != null) {
    const info = db.prepare("DELETE FROM notes WHERE id = ?").run(input.id);
    return info.changes > 0
      ? `Forgot note #${input.id}.`
      : `No note #${input.id} to forget.`;
  }
  if (input.key) {
    if (input.confirm !== "yes") {
      return (
        `Refusing bulk delete by key "${input.key}" without confirm:"yes". ` +
        `Re-call with confirm:"yes" to proceed.`
      );
    }
    const info = db.prepare("DELETE FROM notes WHERE key = ?").run(input.key);
    return `Forgot ${info.changes} note(s) under key "${input.key}".`;
  }
  return "forget: provide either `id` (single) or `key` + `confirm:\"yes\"` (bulk).";
}

export function handlePin(db: DatabaseSync, input: PinInput): string {
  const pinned = input.pinned === false ? 0 : 1;
  const info = db.prepare("UPDATE notes SET pinned = ? WHERE id = ?").run(pinned, input.id);
  if (info.changes === 0) return `No note #${input.id} to ${pinned ? "pin" : "unpin"}.`;
  return pinned ? `Pinned note #${input.id}.` : `Unpinned note #${input.id}.`;
}

export function handleJournal(
  db: DatabaseSync,
  input: JournalInput,
  currentRepo: string | null,
): string {
  if (!currentRepo) {
    return "Not in a recognized git repository; no scoped activity.";
  }
  const rows = db
    .prepare(
      "SELECT e.tool, e.file_path, e.ts FROM edits e JOIN sessions s ON e.session_id = s.id " +
        "WHERE s.repo = ? ORDER BY e.id DESC LIMIT ?",
    )
    .all(currentRepo, input.limit ?? 20) as Array<{
    tool: string;
    file_path: string | null;
    ts: string;
  }>;
  if (rows.length === 0) return `No recorded edits for ${currentRepo} yet.`;
  const text = rows.map((r) => `${r.ts}  ${r.tool}  ${r.file_path ?? "(no path)"}`).join("\n");
  return `Recent edits for ${currentRepo}:\n${text}`;
}

/**
 * PURE: format a context-budget report from the latest transcript usage (the server resolves the
 * transcript and reads `usage`, passing it in — keeping fs IO out of the handler). Tiered advice
 * nudges toward /checkpoint + /compact as occupancy climbs. `usage === null` means the transcript
 * couldn't be read.
 */
export function handleContextBudget(usage: ContextUsage | null, windowTokens: number): string {
  if (!usage) {
    return (
      "Couldn't read the current session transcript to measure context usage " +
      "(no transcript found, or it has no token data yet)."
    );
  }
  const b = formatBudget(liveContextTokens(usage), windowTokens);
  const advice =
    b.tier === "high"
      ? "Context is nearly full — run /checkpoint to save a handoff, then /compact (or /clear)."
      : b.tier === "warn"
        ? "Context is getting large — consider /checkpoint then /compact at the next natural break."
        : "Plenty of headroom.";
  return `Context budget: ${b.label}. ${advice}`;
}

/** PURE-ish: fetch tag arrays for the given note ids, keyed by note id. */
function fetchTagsFor(db: DatabaseSync, ids: number[]): Map<number, string[]> {
  const out = new Map<number, string[]>();
  if (ids.length === 0) return out;
  const placeholders = ids.map(() => "?").join(", ");
  const rows = db
    .prepare(`SELECT note_id, tag FROM note_tags WHERE note_id IN (${placeholders}) ORDER BY tag ASC`)
    .all(...ids) as Array<{ note_id: number; tag: string }>;
  for (const r of rows) {
    const arr = out.get(r.note_id) ?? [];
    arr.push(r.tag);
    out.set(r.note_id, arr);
  }
  return out;
}
