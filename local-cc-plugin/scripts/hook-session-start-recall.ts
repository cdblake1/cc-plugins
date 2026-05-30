// SessionStart hook (v3 keystone, v5 handoff, v6 pin): inject this repo's memory into context so
// cross-session memory reaches the model. Stdout on a SessionStart hook is added to Claude's
// context. Best-effort and non-blocking — always exits 0.
//
// Block order (most-important first, within MAX_OUTPUT budget):
//   1. pinned notes (always-surface project facts)
//   2. handoff: most recent /checkpoint, then the PreCompact compact-handoff, then the auto
//      session-rollup (preference order below)
//   3. recent earlier notes (excluding pinned + handoff ids already shown, and excluding the
//      deterministic activity dumps — session-rollup + compact-handoff — that would crowd out
//      hand-written notes; the freshest of those still surfaces via the handoff fallback)

import { openDb } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { gitContext } from "./gitctx.ts";

const MAX_NOTES = 8;
const MAX_BODY = 220;
const MAX_HANDOFF = 700;
const MAX_OUTPUT = 2400;
const MAX_PINNED = 3;
const HANDOFF_KEYS = ["checkpoint", "compact-handoff", "session-rollup"];

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
  let pinned: NoteRow[];
  let handoff: NoteRow | undefined;
  let recent: NoteRow[];
  try {
    pinned = db
      .prepare(
        `SELECT id, key, body FROM notes WHERE ${scopeSql} AND pinned = 1 ORDER BY id DESC LIMIT ?`,
      )
      .all(...scopeParams, MAX_PINNED) as NoteRow[];

    const pinnedIds = pinned.map((p) => p.id);
    const exclPinnedSql = pinnedIds.length
      ? ` AND id NOT IN (${pinnedIds.map(() => "?").join(", ")})`
      : "";

    const placeholders = HANDOFF_KEYS.map(() => "?").join(", ");
    // Lead with the most recent *checkpoint* (deliberate, model-written handoff), then the
    // PreCompact compact-handoff (mid-session, machine-written), then the auto session-rollup
    // (end-of-session). The rank prevents a newer-id machine note from shadowing a real checkpoint
    // from the same session.
    handoff = db
      .prepare(
        `SELECT id, key, body FROM notes WHERE ${scopeSql}${exclPinnedSql} AND key IN (${placeholders}) ` +
          `ORDER BY CASE key WHEN 'checkpoint' THEN 0 WHEN 'compact-handoff' THEN 1 ELSE 2 END ASC, id DESC LIMIT 1`,
      )
      .get(...scopeParams, ...pinnedIds, ...HANDOFF_KEYS) as NoteRow | undefined;

    const exclHandoffSql = handoff ? " AND id <> ?" : "";
    // `key IS NULL` matches notes with no key; the NOT IN (...) matches everything else except the
    // deterministic activity dumps (session-rollup + compact-handoff), which are excluded here so
    // they don't crowd the recent block — the freshest already surfaces as the handoff above.
    // NULL-safe — a bare `key NOT IN (...)` would drop keyless notes (NULL comparisons yield NULL).
    const exclRollupSql = " AND (key IS NULL OR key NOT IN ('session-rollup', 'compact-handoff'))";
    recent = db
      .prepare(
        `SELECT id, key, body FROM notes WHERE ${scopeSql}${exclPinnedSql}${exclHandoffSql}${exclRollupSql} ORDER BY id DESC LIMIT ?`,
      )
      .all(...scopeParams, ...pinnedIds, ...(handoff ? [handoff.id] : []), MAX_NOTES) as NoteRow[];
  } finally {
    db.close();
  }

  const scopeLabel = repo ? ` for ${repo}` : "";
  const blocks: string[] = [];

  if (pinned.length > 0) {
    const lines = pinned.map((r) => `- ${r.key ? `[${r.key}] ` : ""}${clip(r.body, MAX_BODY)}`);
    blocks.push(`pinned context${scopeLabel}:\n${lines.join("\n")}`);
  }
  if (handoff) {
    blocks.push(
      `session-journal — picking up${scopeLabel} (last session):\n${clip(handoff.body, MAX_HANDOFF)}`,
    );
  }
  if (recent.length > 0) {
    const lines = recent.map((r) => `- ${r.key ? `[${r.key}] ` : ""}${clip(r.body, MAX_BODY)}`);
    const heading =
      pinned.length > 0 || handoff
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
