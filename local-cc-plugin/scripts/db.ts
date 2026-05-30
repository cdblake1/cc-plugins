// Shared SQLite layer for the session-journal plugin.
// Uses the built-in node:sqlite (no third-party dependency). Requires Node >= 22.6.0
// and is run via `node --experimental-strip-types` (no build step).
//
// The store lives at ${CLAUDE_PLUGIN_DATA}/state.db, the only directory that
// survives plugin updates and reinstalls.

import { DatabaseSync } from "node:sqlite";
import { join, dirname } from "node:path";
import { mkdirSync } from "node:fs";

/** ISO-8601 UTC timestamp, used for every *_at / ts column. */
export function now(): string {
  return new Date().toISOString();
}

/** Persistent data directory provided to plugin subprocesses. */
export function dataDir(): string {
  const dir = process.env.CLAUDE_PLUGIN_DATA;
  if (!dir) {
    throw new Error("CLAUDE_PLUGIN_DATA is not set (expected for plugin subprocesses)");
  }
  return dir;
}

/** Absolute path to the SQLite store. Override `dbPath` only for tests. */
export function dbFile(dbPath?: string): string {
  return dbPath ?? join(dataDir(), "state.db");
}

/**
 * Open (creating if needed) the store and ensure the schema exists.
 * Safe to call from every hook invocation and from the MCP server.
 */
export function openDb(dbPath?: string): DatabaseSync {
  const path = dbFile(dbPath);
  mkdirSync(dirname(path), { recursive: true });

  const db = new DatabaseSync(path);
  // WAL lets the hooks and the MCP server touch the DB concurrently;
  // busy_timeout avoids "database is locked" when a write races a write.
  db.exec("PRAGMA journal_mode = WAL;");
  db.exec("PRAGMA busy_timeout = 5000;");
  db.exec("PRAGMA foreign_keys = ON;");
  migrate(db);
  return db;
}

/**
 * Minimal schema (CLAUDE.md data model). `sessions.id` is the harness session_id
 * (a string) so hooks can correlate edits/notes without tracking a "current" row.
 * Migrations can come later; for now this is create-if-not-exists only.
 */
function migrate(db: DatabaseSync): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS sessions (
      id          TEXT PRIMARY KEY,
      started_at  TEXT NOT NULL,
      ended_at    TEXT,
      cwd         TEXT,
      repo        TEXT,
      branch      TEXT,
      commit_sha  TEXT
    );

    CREATE TABLE IF NOT EXISTS edits (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id  TEXT,
      tool        TEXT NOT NULL,
      file_path   TEXT,
      ts          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notes (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id  TEXT,
      repo        TEXT,
      key         TEXT,
      body        TEXT NOT NULL,
      ts          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS guardrail (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id  TEXT,
      command     TEXT NOT NULL,
      decision    TEXT NOT NULL,  -- 'allow' | 'ask' | 'deny'
      reason      TEXT,
      ts          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS checks (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id  TEXT,
      kind        TEXT NOT NULL,  -- 'format' | 'lint' | 'test'
      command     TEXT NOT NULL,
      ok          INTEGER NOT NULL,  -- 1 pass, 0 fail
      output      TEXT,
      ts          TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_edits_session ON edits(session_id);
    CREATE INDEX IF NOT EXISTS idx_notes_key     ON notes(key);
    CREATE INDEX IF NOT EXISTS idx_checks_session ON checks(session_id);
  `);

  // Migrate DBs created before v3: add git-scoping columns if missing, then index notes.repo.
  addColumnIfMissing(db, "sessions", "repo", "TEXT");
  addColumnIfMissing(db, "sessions", "branch", "TEXT");
  addColumnIfMissing(db, "sessions", "commit_sha", "TEXT");
  addColumnIfMissing(db, "notes", "repo", "TEXT");
  db.exec("CREATE INDEX IF NOT EXISTS idx_notes_repo ON notes(repo);");

  // v6: pinned flag, tags, and FTS5 over note bodies.
  addColumnIfMissing(db, "notes", "pinned", "INTEGER NOT NULL DEFAULT 0");
  db.exec(`
    CREATE TABLE IF NOT EXISTS note_tags (
      note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
      tag     TEXT NOT NULL,
      PRIMARY KEY (note_id, tag)
    );
    CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);

    CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
      body, content='notes', content_rowid='id'
    );

    -- Keep notes_fts in sync with notes.body.
    CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
      INSERT INTO notes_fts(rowid, body) VALUES (new.id, new.body);
    END;
    CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
      INSERT INTO notes_fts(notes_fts, rowid, body) VALUES('delete', old.id, old.body);
    END;
    CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
      INSERT INTO notes_fts(notes_fts, rowid, body) VALUES('delete', old.id, old.body);
      INSERT INTO notes_fts(rowid, body) VALUES (new.id, new.body);
    END;
  `);

  // One-time FTS rebuild when crossing into v6. We track this via PRAGMA user_version (a built-in
  // 32-bit slot SQLite reserves for app schema versions — no extra table needed). Can't gate on
  // `COUNT(*) FROM notes_fts` because external-content FTS5 always reports the content table's
  // count regardless of whether the index is populated.
  const userVersion = (db.prepare("PRAGMA user_version").get() as { user_version: number }).user_version;
  if (userVersion < 6) {
    db.exec("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')");
    db.exec("PRAGMA user_version = 6");
  }
}

/** Add a column only if it isn't already present (SQLite has no ADD COLUMN IF NOT EXISTS). */
function addColumnIfMissing(db: DatabaseSync, table: string, col: string, decl: string): void {
  const cols = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>;
  if (!cols.some((c) => c.name === col)) {
    db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${decl}`);
  }
}
