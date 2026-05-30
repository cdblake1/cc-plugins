// Rollup helpers for the v5 auto-capture (the deterministic end-of-session note).
// The top half is pure formatting (unit-tested without a DB); the bottom half is a single
// DB-touching retention helper (unit-tested against a tmp SQLite, like mcp/handlers.ts).

import type { DatabaseSync } from "node:sqlite";

/** Default retention for `session-rollup` notes per repo. The freshest rollup still surfaces
 * via the SessionStart handoff fallback; older ones add little signal since the next session
 * usually has its own /checkpoint. Raw activity stays searchable via the `edits` table. */
export const ROLLUP_RETENTION = 5;

/** Key + retention for the v7 PreCompact handoff note (written before context compaction).
 * These are even more transient than rollups — only the freshest matters as a "what was in
 * flight when we compacted" handoff — so we keep fewer. */
export const COMPACT_HANDOFF_KEY = "compact-handoff";
export const COMPACT_HANDOFF_RETENTION = 3;

export type EditRow = { tool: string; file_path: string | null; ts: string };
export type SessionRow = {
  started_at: string | null;
  ended_at: string | null;
  branch: string | null;
  commit_sha: string | null;
};

/** PURE: human-readable elapsed time between two ISO timestamps ("<1m" / "25m" / "1h 3m"). */
export function formatDuration(startIso: string | null, endIso: string | null): string | null {
  if (!startIso || !endIso) return null;
  const ms = Date.parse(endIso) - Date.parse(startIso);
  if (!Number.isFinite(ms) || ms < 0) return null;
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "<1m";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** PURE: last path segment, handling both `/` and `\` separators. */
export function baseName(p: string): string {
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : p;
}

/**
 * PURE: drop edits whose file no longer exists at session end, per the given `exists` predicate
 * (the hook passes `fs.existsSync`). This keeps transient scratch/temp files that were created and
 * later deleted out of the rollup. Edits with no file_path are kept — they still represent activity.
 */
export function liveEdits(edits: EditRow[], exists: (p: string) => boolean): EditRow[] {
  return edits.filter((e) => !e.file_path || exists(e.file_path));
}

/**
 * PURE: build the deterministic session-rollup note body from a session and its edits.
 * Returns null when there's nothing worth recording (no edits) — the hook then skips the insert,
 * so read-only sessions don't clutter the store.
 */
export function formatRollup(session: SessionRow, edits: EditRow[], maxFiles = 8): string | null {
  if (edits.length === 0) return null;

  const files = [...new Set(edits.map((e) => e.file_path).filter((f): f is string => !!f))];
  const shown = files.slice(0, maxFiles).map(baseName);
  const more = files.length > maxFiles ? ` +${files.length - maxFiles} more` : "";

  const dur = formatDuration(session.started_at, session.ended_at);
  const ctx = [
    session.branch ? `branch ${session.branch}` : null,
    session.commit_sha ? `@${session.commit_sha}` : null,
    dur ? `~${dur}` : null,
  ]
    .filter(Boolean)
    .join(", ");

  const editN = `${edits.length} edit${edits.length === 1 ? "" : "s"}`;
  const fileN = `${files.length} file${files.length === 1 ? "" : "s"}`;
  const fileList = files.length ? `: ${shown.join(", ")}${more}` : "";

  return `Auto session rollup${ctx ? ` (${ctx})` : ""} — ${editN} across ${fileN}${fileList}.`;
}

/**
 * PURE: build the PreCompact handoff body. Reuses the deterministic rollup summary verbatim and
 * prefixes a compaction marker (with the trigger when known) so the next session reads it as
 * "we compacted here, this was in flight". Returns null when there's no rollup (no edits) — the
 * hook then skips the insert, so read-only sessions don't leave a compaction note.
 */
export function formatCompactHandoff(
  rollupBody: string | null,
  trigger: string | null,
): string | null {
  if (!rollupBody) return null;
  const tg = trigger === "manual" || trigger === "auto" ? ` (${trigger})` : "";
  return `Context compacted${tg}. ${rollupBody}`;
}

/**
 * Prune older notes with a given `key` within a repo scope, keeping the `keep` most recent.
 * Pinned notes (if a user explicitly pinned one) are preserved unconditionally.
 *
 * Scope semantics match how these notes are stored: a row with `repo = null` is "no-repo session"
 * and is pruned only against other no-repo notes of the same key. We use `IS NOT DISTINCT FROM` so
 * the same statement handles both cases without a NULL-vs-equality branch. Returns the number
 * deleted. Used for both `session-rollup` (SessionEnd) and `compact-handoff` (PreCompact) notes.
 */
export function pruneOldNotesByKey(
  db: DatabaseSync,
  key: string,
  repo: string | null,
  keep: number,
): number {
  if (keep < 0) return 0;
  const info = db
    .prepare(
      `DELETE FROM notes
       WHERE id IN (
         SELECT id FROM notes
         WHERE key = ?
           AND repo IS NOT DISTINCT FROM ?
           AND pinned = 0
         ORDER BY id DESC
         LIMIT -1 OFFSET ?
       )`,
    )
    .run(key, repo, keep);
  return Number(info.changes);
}

/** Thin wrapper preserving the original `session-rollup` call site + semantics. */
export function pruneOldRollups(
  db: DatabaseSync,
  repo: string | null,
  keep: number = ROLLUP_RETENTION,
): number {
  return pruneOldNotesByKey(db, "session-rollup", repo, keep);
}
