// SessionEnd hook: stamp the session's ended_at, then (v5 auto-capture) write a deterministic
// rollup note so cross-session memory is never empty even when nobody stored a note.
//
// The rollup is plain SQLite (no model invocation) so it works everywhere, including headless
// `-p`/CI runs where model-invoking `agent` hooks are unsupported. SessionEnd blocks on command
// hooks, so this completes before teardown. Opt out by setting userConfig auto_rollup = "off".
import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { formatRollup, type EditRow, type SessionRow } from "./rollup.ts";

try {
  const input = await readHookInput<{ session_id?: string }>();
  const id = input.session_id;
  if (id) {
    const db = openDb();
    try {
      const endedAt = now();
      db.prepare("UPDATE sessions SET ended_at = ? WHERE id = ?").run(endedAt, id);

      if (process.env.CLAUDE_PLUGIN_OPTION_AUTO_ROLLUP !== "off") {
        const session = db
          .prepare(
            "SELECT started_at, ended_at, repo, branch, commit_sha FROM sessions WHERE id = ?",
          )
          .get(id) as (SessionRow & { repo: string | null }) | undefined;
        if (session) {
          const edits = db
            .prepare("SELECT tool, file_path, ts FROM edits WHERE session_id = ? ORDER BY id ASC")
            .all(id) as EditRow[];
          const body = formatRollup({ ...session, ended_at: endedAt }, edits);
          if (body) {
            db.prepare(
              "INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)",
            ).run(id, session.repo, "session-rollup", body, endedAt);
          }
        }
      }
    } finally {
      db.close();
    }
  }
} catch (err) {
  console.error("session-journal session-end hook:", (err as Error).message);
}
process.exit(0);
