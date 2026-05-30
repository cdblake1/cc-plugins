// PreCompact hook (v7 context-efficiency): before context compaction — manual (`/compact`) or
// auto (the context window filling up) — persist a deterministic handoff note from the edits
// journal so detail that compaction would discard isn't lost. It resurfaces via the existing
// SessionStart auto-recall (ranked below a real /checkpoint) and the `recall` tool. This makes
// compacting/clearing *safe*, so context can stay lean without fear of losing the thread.
//
// No model invocation (PreCompact cannot call Claude, and cannot inject into the post-compaction
// summary) — the note is built deterministically from the `edits` table, mirroring the SessionEnd
// rollup. Plain SQLite, best-effort, never blocks: always exits 0.
import { existsSync } from "node:fs";
import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import {
  formatRollup,
  formatCompactHandoff,
  liveEdits,
  pruneOldNotesByKey,
  COMPACT_HANDOFF_KEY,
  COMPACT_HANDOFF_RETENTION,
  type EditRow,
  type SessionRow,
} from "./rollup.ts";

try {
  const input = await readHookInput<{ session_id?: string; trigger?: string }>();
  const id = input.session_id;
  if (id) {
    const db = openDb();
    try {
      const session = db
        .prepare("SELECT started_at, ended_at, repo, branch, commit_sha FROM sessions WHERE id = ?")
        .get(id) as (SessionRow & { repo: string | null }) | undefined;
      if (session) {
        const edits = db
          .prepare("SELECT tool, file_path, ts FROM edits WHERE session_id = ? ORDER BY id ASC")
          .all(id) as EditRow[];
        const ts = now();
        // Compaction is a mid-session checkpoint, not an end → synthesize ended_at so the rollup's
        // duration reflects time-into-session. Drop edits to files deleted during the session.
        const rollup = formatRollup({ ...session, ended_at: ts }, liveEdits(edits, existsSync));
        const body = formatCompactHandoff(rollup, input.trigger ?? null);
        // No edits → no rollup → no note (read-only stretches don't leave compaction clutter).
        if (body) {
          db.prepare(
            "INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)",
          ).run(id, session.repo, COMPACT_HANDOFF_KEY, body, ts);
          // Keep only the freshest few per repo; pinned ones preserved.
          pruneOldNotesByKey(db, COMPACT_HANDOFF_KEY, session.repo, COMPACT_HANDOFF_RETENTION);
        }
      }
    } finally {
      db.close();
    }
  }
} catch (err) {
  console.error("session-journal precompact hook:", (err as Error).message);
}
process.exit(0);
