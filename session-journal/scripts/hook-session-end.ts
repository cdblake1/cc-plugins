// SessionEnd hook: stamp the session's ended_at.
import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";

try {
  const input = await readHookInput<{ session_id?: string }>();
  const id = input.session_id;
  if (id) {
    const db = openDb();
    try {
      db.prepare("UPDATE sessions SET ended_at = ? WHERE id = ?").run(now(), id);
    } finally {
      db.close();
    }
  }
} catch (err) {
  console.error("session-journal session-end hook:", (err as Error).message);
}
process.exit(0);
