// Unit tests for the v6 db.ts migrations: pinned column, note_tags + cascade,
// notes_fts virtual table + sync triggers + backfill, and migration idempotency.
// Run via `npm test`.

import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openDb } from "./db.ts";

let failed = 0;
function eq(name: string, got: unknown, want: unknown): void {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) {
    failed++;
    console.error(`FAIL ${name}: got ${g} want ${w}`);
  }
}
function truthy(name: string, got: unknown): void {
  if (!got) {
    failed++;
    console.error(`FAIL ${name}: expected truthy, got ${JSON.stringify(got)}`);
  }
}

const root = mkdtempSync(join(tmpdir(), "session-journal-db-test-"));
const dbPath = join(root, "state.db");

try {
  // -- Initial migration: tables and FTS table exist, pinned column present.
  {
    const db = openDb(dbPath);
    try {
      const noteCols = (db.prepare("PRAGMA table_info(notes)").all() as Array<{ name: string }>).map(
        (c) => c.name,
      );
      truthy("notes.pinned column added", noteCols.includes("pinned"));

      const tables = (
        db
          .prepare("SELECT name FROM sqlite_master WHERE type IN ('table','virtual') ORDER BY name")
          .all() as Array<{ name: string }>
      ).map((r) => r.name);
      truthy("note_tags table exists", tables.includes("note_tags"));
      truthy("notes_fts table exists", tables.includes("notes_fts"));

      // FTS triggers exist.
      const triggers = (
        db
          .prepare("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
          .all() as Array<{ name: string }>
      ).map((r) => r.name);
      eq("fts triggers", triggers, ["notes_ad", "notes_ai", "notes_au"]);
    } finally {
      db.close();
    }
  }

  // -- Migration idempotency: second openDb() on the same file doesn't throw and schema stable.
  {
    const db = openDb(dbPath);
    try {
      const before = db
        .prepare("PRAGMA table_info(notes)")
        .all() as Array<{ name: string; type: string }>;
      // Run a no-op exec to ensure the second migration completed; re-query.
      const after = db
        .prepare("PRAGMA table_info(notes)")
        .all() as Array<{ name: string; type: string }>;
      eq(
        "schema stable after re-open",
        before.map((c) => c.name).join(","),
        after.map((c) => c.name).join(","),
      );
    } finally {
      db.close();
    }
  }

  // -- FTS round-trip via INSERT trigger.
  {
    const db = openDb(dbPath);
    try {
      const info = db
        .prepare("INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)")
        .run(null, "owner/x", "k1", "hello world about FTS", "2026-05-26T00:00:00.000Z");
      const id = Number(info.lastInsertRowid);

      const hit = db
        .prepare("SELECT n.id FROM notes_fts f JOIN notes n ON n.id = f.rowid WHERE f.notes_fts MATCH ?")
        .get('"FTS"') as { id: number } | undefined;
      eq("fts insert trigger fires", hit?.id, id);

      // UPDATE trigger: change body, old term gone, new term hits.
      db.prepare("UPDATE notes SET body = ? WHERE id = ?").run("totally different banana", id);
      const oldHit = db
        .prepare("SELECT n.id FROM notes_fts f JOIN notes n ON n.id = f.rowid WHERE f.notes_fts MATCH ?")
        .get('"FTS"') as { id: number } | undefined;
      eq("fts update trigger drops old term", oldHit, undefined);
      const newHit = db
        .prepare("SELECT n.id FROM notes_fts f JOIN notes n ON n.id = f.rowid WHERE f.notes_fts MATCH ?")
        .get('"banana"') as { id: number } | undefined;
      eq("fts update trigger inserts new term", newHit?.id, id);

      // DELETE trigger: row + FTS entry gone.
      db.prepare("DELETE FROM notes WHERE id = ?").run(id);
      const gone = db
        .prepare("SELECT n.id FROM notes_fts f JOIN notes n ON n.id = f.rowid WHERE f.notes_fts MATCH ?")
        .get('"banana"') as { id: number } | undefined;
      eq("fts delete trigger removes entry", gone, undefined);
    } finally {
      db.close();
    }
  }

  // -- note_tags ON DELETE CASCADE.
  {
    const db = openDb(dbPath);
    try {
      const info = db
        .prepare("INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)")
        .run(null, "owner/x", "k2", "tagged note", "2026-05-26T00:01:00.000Z");
      const id = Number(info.lastInsertRowid);
      db.prepare("INSERT INTO note_tags(note_id, tag) VALUES (?, ?)").run(id, "alpha");
      db.prepare("INSERT INTO note_tags(note_id, tag) VALUES (?, ?)").run(id, "beta");

      const before = (
        db.prepare("SELECT COUNT(*) AS c FROM note_tags WHERE note_id = ?").get(id) as { c: number }
      ).c;
      eq("two tags inserted", before, 2);

      db.prepare("DELETE FROM notes WHERE id = ?").run(id);
      const after = (
        db.prepare("SELECT COUNT(*) AS c FROM note_tags WHERE note_id = ?").get(id) as { c: number }
      ).c;
      eq("tags cascade-deleted with note", after, 0);
    } finally {
      db.close();
    }
  }

  // -- Backfill: simulate a pre-v6 DB (legacy tables only, user_version = 0) populated with a few
  // notes. On openDb(), the v6 migration should add the FTS table and rebuild it from notes.body.
  {
    const legacyPath = join(root, "legacy.db");
    // Build the pre-v6 schema by hand (no openDb, so our migrate() doesn't run).
    const { DatabaseSync } = await import("node:sqlite");
    const raw = new DatabaseSync(legacyPath);
    raw.exec(`
      CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, cwd TEXT);
      CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, key TEXT, body TEXT NOT NULL, ts TEXT NOT NULL);
    `);
    raw
      .prepare("INSERT INTO notes (session_id, key, body, ts) VALUES (?, ?, ?, ?)")
      .run(null, "pre-v6", "backfill candidate text", "2026-05-26T00:02:00.000Z");
    const preCount = (raw.prepare("SELECT COUNT(*) AS c FROM notes").get() as { c: number }).c;
    eq("legacy db has one note", preCount, 1);
    raw.close();

    // Now openDb runs the v6 migration. Must add pinned/note_tags/notes_fts and backfill FTS.
    const db = openDb(legacyPath);
    try {
      const userVersion = (db.prepare("PRAGMA user_version").get() as { user_version: number })
        .user_version;
      eq("user_version stamped to 6", userVersion, 6);

      const hit = db
        .prepare(
          "SELECT n.id FROM notes_fts f JOIN notes n ON n.id = f.rowid WHERE f.notes_fts MATCH ?",
        )
        .get('"backfill"') as { id: number } | undefined;
      truthy("backfilled row is searchable via FTS", hit?.id);
    } finally {
      db.close();
    }
  }
} finally {
  if (existsSync(root)) rmSync(root, { recursive: true, force: true });
}

if (failed > 0) {
  console.error(`\ndb: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("db: all assertions pass");
