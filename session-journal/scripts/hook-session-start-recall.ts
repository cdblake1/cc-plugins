// SessionStart hook (v3 keystone): inject this repo's recent notes into context so
// cross-session memory actually reaches the model. Stdout on a SessionStart hook is added
// to Claude's context. Best-effort and non-blocking — always exits 0.

import { openDb } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { gitContext } from "./gitctx.ts";

const MAX_NOTES = 10;
const MAX_BODY = 200;
const MAX_OUTPUT = 2000;

try {
  const input = await readHookInput<{ cwd?: string }>();
  const { repo } = gitContext(input.cwd ?? process.cwd());

  const db = openDb();
  let rows: Array<{ key: string | null; body: string }>;
  try {
    // Scope to this repo (plus legacy/global notes with no repo); newest first.
    rows = repo
      ? (db
          .prepare(
            "SELECT key, body FROM notes WHERE repo = ? OR repo IS NULL ORDER BY id DESC LIMIT ?",
          )
          .all(repo, MAX_NOTES) as Array<{ key: string | null; body: string }>)
      : (db
          .prepare("SELECT key, body FROM notes ORDER BY id DESC LIMIT ?")
          .all(MAX_NOTES) as Array<{ key: string | null; body: string }>);
  } finally {
    db.close();
  }

  if (rows.length > 0) {
    const lines = rows.map((r) => {
      const body = r.body.length > MAX_BODY ? `${r.body.slice(0, MAX_BODY)}…` : r.body;
      return `- ${r.key ? `[${r.key}] ` : ""}${body}`;
    });
    let out = `session-journal memory${repo ? ` for ${repo}` : ""} (recent notes — use the recall tool for more):\n${lines.join("\n")}`;
    if (out.length > MAX_OUTPUT) out = `${out.slice(0, MAX_OUTPUT)}\n…`;
    process.stdout.write(`${out}\n`);
  }
} catch {
  // Never let auto-recall disrupt a session.
}
process.exit(0);
