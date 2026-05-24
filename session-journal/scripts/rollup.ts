// Pure formatting for the v5 auto-capture rollup (the deterministic end-of-session note).
// Kept side-effect-free so it can be unit-tested without a DB; the SessionEnd hook supplies
// the rows it reads from SQLite. Mirrors the project's pattern of extracting pure logic
// (see guardrail-policy.ts / checks.ts) and testing it directly.

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
