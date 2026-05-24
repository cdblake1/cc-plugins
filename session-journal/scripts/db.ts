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
      cwd         TEXT
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

    CREATE INDEX IF NOT EXISTS idx_edits_session ON edits(session_id);
    CREATE INDEX IF NOT EXISTS idx_notes_key     ON notes(key);
  `);
}
