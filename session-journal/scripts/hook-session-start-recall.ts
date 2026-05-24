// SessionStart hook (v3 keystone, v5 handoff): inject this repo's memory into context so
// cross-session memory reaches the model. Stdout on a SessionStart hook is added to Claude's
// context. Best-effort and non-blocking — always exits 0.
//
// v5: lead with the most recent "handoff" note (a /checkpoint or the auto session-rollup) so a
// new session opens with "here's where we left off", then list earlier notes.

import { openDb } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { gitContext } from "./gitctx.ts";

const MAX_NOTES = 8;
const MAX_BODY = 220;
const MAX_HANDOFF = 700;
const MAX_OUTPUT = 2400;
const HANDOFF_KEYS = ["checkpoint", "session-rollup"];

type NoteRow = { id: number; key: string | null; body: string };

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

try {
  const input = await readHookInput<{ cwd?: string }>();
  const { repo } = gitContext(input.cwd ?? process.cwd());

  // Scope to this repo (plus legacy/global notes with no repo) when we know it; else everything.
  const scopeSql = repo ? "(repo = ? OR repo IS NULL)" : "1 = 1";
  const scopeParams: string[] = repo ? [repo] : [];

  const db = openDb();
  let handoff: NoteRow | undefined;
  let recent: NoteRow[];
  try {
    const placeholders = HANDOFF_KEYS.map(() => "?").join(", ");
    handoff = db
      .prepare(
        `SELECT id, key, body FROM notes WHERE ${scopeSql} AND key IN (${placeholders}) ORDER BY id DESC LIMIT 1`,
      )
      .get(...scopeParams, ...HANDOFF_KEYS) as NoteRow | undefined;

    recent = db
      .prepare(
        `SELECT id, key, body FROM notes WHERE ${scopeSql}${handoff ? " AND id <> ?" : ""} ORDER BY id DESC LIMIT ?`,
      )
      .all(...scopeParams, ...(handoff ? [handoff.id] : []), MAX_NOTES) as NoteRow[];
  } finally {
    db.close();
  }

  const scopeLabel = repo ? ` for ${repo}` : "";
  const blocks: string[] = [];
  if (handoff) {
    blocks.push(`session-journal — picking up${scopeLabel} (last session):\n${clip(handoff.body, MAX_HANDOFF)}`);
  }
  if (recent.length > 0) {
    const lines = recent.map((r) => `- ${r.key ? `[${r.key}] ` : ""}${clip(r.body, MAX_BODY)}`);
    const heading = handoff
      ? "earlier notes (use the recall tool for more):"
      : `session-journal memory${scopeLabel} (recent notes — use the recall tool for more):`;
    blocks.push(`${heading}\n${lines.join("\n")}`);
  }

  if (blocks.length > 0) {
    let out = blocks.join("\n\n");
    if (out.length > MAX_OUTPUT) out = `${out.slice(0, MAX_OUTPUT)}\n…`;
    process.stdout.write(`${out}\n`);
  }
} catch {
  // Never let auto-recall disrupt a session.
}
process.exit(0);
