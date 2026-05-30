// Unit tests for the v6 MCP tool handlers (forget, pin, extended store/recall, journal).
// Exercises the pure-ish handlers against a tmp SQLite DB — no MCP transport, no subprocess.

import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openDb } from "../scripts/db.ts";
import {
  ftsPhrase,
  handleContextBudget,
  handleForget,
  handleJournal,
  handlePin,
  handleRecall,
  handleStore,
  normalizeTags,
} from "./handlers.ts";
import type { ContextUsage } from "../scripts/transcript.ts";

let failed = 0;
function eq(name: string, got: unknown, want: unknown): void {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) {
    failed++;
    console.error(`FAIL ${name}: got ${g} want ${w}`);
  }
}
function contains(name: string, haystack: string, needle: string): void {
  if (!haystack.includes(needle)) {
    failed++;
    console.error(`FAIL ${name}: expected substring '${needle}' in '${haystack}'`);
  }
}
function notContains(name: string, haystack: string, needle: string): void {
  if (haystack.includes(needle)) {
    failed++;
    console.error(`FAIL ${name}: did NOT expect substring '${needle}' in '${haystack}'`);
  }
}

const root = mkdtempSync(join(tmpdir(), "session-journal-handlers-test-"));
const dbPath = join(root, "state.db");

try {
  // -- normalizeTags (pure)
  eq("normalizeTags empty", normalizeTags(undefined), []);
  eq("normalizeTags lower+trim+dedupe", normalizeTags(["  Foo", "foo", "BAR ", ""]), ["foo", "bar"]);

  // -- ftsPhrase (pure)
  eq("ftsPhrase basic", ftsPhrase("hello world"), '"hello world"');
  eq("ftsPhrase escapes quote", ftsPhrase('say "hi"'), '"say ""hi"""');

  // -- handleContextBudget (pure; no DB, no fs — server passes in the usage)
  const usage = (cacheRead: number): ContextUsage => ({ input: 0, cacheRead, cacheCreate: 0, output: 9999 });
  contains("budget null usage explains", handleContextBudget(null, 200000), "Couldn't read");
  const okReport = handleContextBudget(usage(30000), 200000); // 15%
  contains("budget ok shows pct", okReport, "(15%)");
  contains("budget ok advises headroom", okReport, "Plenty of headroom");
  contains("budget warn advises checkpoint", handleContextBudget(usage(140000), 200000), "getting large"); // 70%
  contains("budget high advises compact now", handleContextBudget(usage(180000), 200000), "nearly full"); // 90%
  contains("budget excludes output tokens", okReport, "~30k"); // output (9999) not counted
  contains("budget custom window", handleContextBudget(usage(100000), 1000000), "(10%)");

  const REPO = "owner/repo";
  const OTHER = "owner/other";
  const db = openDb(dbPath);
  try {
    // --- handleStore: with tags, with key, repo-scoped.
    const r1 = handleStore(
      db,
      { body: "first note about FTS search", key: "fts", tags: ["search", "memory"] },
      REPO,
    );
    contains("store text mentions key", r1, '"fts"');
    contains("store text mentions tags", r1, "[search, memory]");
    contains("store text mentions repo", r1, REPO);

    const r2 = handleStore(db, { body: "second note no tags" }, REPO);
    contains("store w/o key still reports", r2, "Stored note #");

    // A note from another repo (for scope tests).
    handleStore(db, { body: "other repo note", key: "fts" }, OTHER);
    // A note with no repo (legacy/global).
    handleStore(db, { body: "global legacy note", key: "fts" }, null);

    // --- handleRecall: default scope returns current repo + global, NOT the other repo.
    const all = handleRecall(db, {}, REPO);
    contains("recall sees current-repo note", all, "first note about FTS search");
    contains("recall sees global note", all, "global legacy note");
    notContains("recall excludes other-repo note by default", all, "other repo note");

    // --- handleRecall: scope=all picks up everything.
    const everyone = handleRecall(db, { scope: "all" }, REPO);
    contains("recall scope=all sees other repo", everyone, "other repo note");

    // --- handleRecall: key filter.
    const byKey = handleRecall(db, { key: "fts" }, REPO);
    contains("recall by key matches", byKey, "first note about FTS search");
    notContains("recall by key excludes mismatched", byKey, "second note no tags");

    // --- handleRecall: tag filter.
    const byTag = handleRecall(db, { tags: ["memory"] }, REPO);
    contains("recall by tag matches", byTag, "first note about FTS search");
    notContains("recall by tag excludes untagged", byTag, "second note no tags");

    // --- handleRecall: FTS query.
    const byQuery = handleRecall(db, { query: "FTS" }, REPO);
    contains("recall by FTS query matches", byQuery, "first note about FTS search");
    notContains("recall by FTS query excludes mismatch", byQuery, "second note no tags");

    // --- handleRecall: since/until.
    const sinceNow = handleRecall(
      db,
      { since: "2099-01-01T00:00:00.000Z" },
      REPO,
    );
    eq("recall since-future returns nothing", sinceNow, "No matching notes.");

    // --- handlePin + handleRecall pinned indicator.
    // Grab note #1 id from the recall output — easier to query the DB directly.
    const firstId = (
      db
        .prepare("SELECT id FROM notes WHERE body = ?")
        .get("first note about FTS search") as { id: number }
    ).id;
    const pinResult = handlePin(db, { id: firstId, pinned: true });
    contains("pin reports success", pinResult, `Pinned note #${firstId}`);
    const afterPin = handleRecall(db, { key: "fts" }, REPO);
    contains("recall shows pin emoji", afterPin, "📌");

    const unpinResult = handlePin(db, { id: firstId, pinned: false });
    contains("unpin reports success", unpinResult, `Unpinned note #${firstId}`);

    const pinMissing = handlePin(db, { id: 999999 });
    contains("pin missing id reports", pinMissing, "No note #999999");

    // --- handleForget: single id.
    const r3 = handleStore(db, { body: "ephemeral note" }, REPO);
    const ephemeralId = Number(r3.match(/#(\d+)/)?.[1]);
    const forget1 = handleForget(db, { id: ephemeralId });
    contains("forget by id reports", forget1, `Forgot note #${ephemeralId}`);
    const forget1again = handleForget(db, { id: ephemeralId });
    contains("forget missing id reports", forget1again, "No note");

    // --- handleForget: bulk by key requires confirm.
    const refuse = handleForget(db, { key: "fts" });
    contains("forget by key without confirm refuses", refuse, "Refusing bulk delete");
    // Notes with key=fts should still be there.
    const stillThere = handleRecall(db, { key: "fts" }, REPO);
    contains("notes survive refused bulk delete", stillThere, "first note about FTS search");

    const wiped = handleForget(db, { key: "fts", confirm: "yes" });
    contains("forget by key with confirm proceeds", wiped, 'under key "fts"');
    const goneNow = handleRecall(db, { key: "fts" }, REPO);
    eq("notes gone after bulk delete", goneNow, "No matching notes.");

    // --- handleForget: misuse (no id, no key).
    const misuse = handleForget(db, {});
    contains("forget with no args explains", misuse, "provide either");

    // --- handleJournal: empty for repo with no edits.
    const jEmpty = handleJournal(db, {}, REPO);
    contains("journal reports empty", jEmpty, "No recorded edits");

    // Insert a session + edit and verify journal picks it up.
    db.prepare(
      "INSERT INTO sessions (id, started_at, repo) VALUES (?, ?, ?)",
    ).run("sess1", "2026-05-26T00:00:00.000Z", REPO);
    db.prepare("INSERT INTO edits (session_id, tool, file_path, ts) VALUES (?, ?, ?, ?)").run(
      "sess1",
      "Edit",
      "/x/foo.ts",
      "2026-05-26T00:01:00.000Z",
    );
    const jHit = handleJournal(db, {}, REPO);
    contains("journal shows edit", jHit, "/x/foo.ts");

    // --- handleJournal: not in a repo.
    const jNoRepo = handleJournal(db, {}, null);
    contains("journal explains no-repo case", jNoRepo, "Not in a recognized git repository");
  } finally {
    db.close();
  }
} finally {
  if (existsSync(root)) rmSync(root, { recursive: true, force: true });
}

if (failed > 0) {
  console.error(`\nhandlers: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("handlers: all assertions pass");
