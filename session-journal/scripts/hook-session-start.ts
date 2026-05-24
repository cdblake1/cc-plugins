// SessionStart hook: record the session row. Idempotent across startup/resume/clear.
import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { gitContext } from "./gitctx.ts";

try {
  const input = await readHookInput<{ session_id?: string; cwd?: string }>();
  const id = input.session_id;
  if (id) {
    const cwd = input.cwd ?? null;
    const { repo, branch, commit } = gitContext(cwd ?? process.cwd());
    const db = openDb();
    try {
      db.prepare(
        "INSERT INTO sessions (id, started_at, cwd, repo, branch, commit_sha) " +
          "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
      ).run(id, now(), cwd, repo, branch, commit);
    } finally {
      db.close();
    }
  }
} catch (err) {
  console.error("session-journal session-start hook:", (err as Error).message);
}
process.exit(0);
