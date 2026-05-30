// Unit tests for rollup helpers (v5 auto-capture pure formatters + v0.6.0 retention).
// Run via `npm test`.
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openDb } from "./db.ts";
import {
  formatDuration,
  baseName,
  formatRollup,
  formatCompactHandoff,
  liveEdits,
  pruneOldRollups,
  pruneOldNotesByKey,
  ROLLUP_RETENTION,
  COMPACT_HANDOFF_KEY,
  COMPACT_HANDOFF_RETENTION,
  type EditRow,
} from "./rollup.ts";

let failed = 0;
function eq(name: string, got: string | null, want: string | null): void {
  if (got !== want) {
    failed++;
    console.error(`FAIL ${name}: got '${got}' want '${want}'`);
  }
}

const T0 = "2026-05-24T03:00:00.000Z";
const edit = (file_path: string | null): EditRow => ({ tool: "Edit", file_path, ts: T0 });

// formatDuration
eq("dur-null-start", formatDuration(null, T0), null);
eq("dur-null-end", formatDuration(T0, null), null);
eq("dur-negative", formatDuration("2026-05-24T03:10:00.000Z", T0), null);
eq("dur-sub-minute", formatDuration(T0, "2026-05-24T03:00:30.000Z"), "<1m");
eq("dur-minutes", formatDuration(T0, "2026-05-24T03:25:00.000Z"), "25m");
eq("dur-hours-exact", formatDuration(T0, "2026-05-24T05:00:00.000Z"), "2h");
eq("dur-hours-mins", formatDuration(T0, "2026-05-24T04:03:00.000Z"), "1h 3m");

// baseName (cross-platform)
eq("base-win", baseName("C:\\repos\\claude-plugin\\db.ts"), "db.ts");
eq("base-posix", baseName("/home/u/proj/server.ts"), "server.ts");
eq("base-plain", baseName("file.md"), "file.md");

// formatRollup
const sess = { started_at: T0, ended_at: "2026-05-24T03:25:00.000Z", branch: "main", commit_sha: "abc1234" };

eq("rollup-empty", formatRollup(sess, []), null);

eq(
  "rollup-basic",
  formatRollup(sess, [edit("C:\\r\\a.ts"), edit("C:\\r\\b.ts"), edit("C:\\r\\a.ts")]),
  "Auto session rollup (branch main, @abc1234, ~25m) — 3 edits across 2 files: a.ts, b.ts.",
);

eq(
  "rollup-singular",
  formatRollup({ started_at: T0, ended_at: T0, branch: null, commit_sha: null }, [edit("/x/one.ts")]),
  "Auto session rollup (~<1m) — 1 edit across 1 file: one.ts.",
);

eq(
  "rollup-no-context",
  formatRollup({ started_at: null, ended_at: null, branch: null, commit_sha: null }, [edit("/x/q.ts")]),
  "Auto session rollup — 1 edit across 1 file: q.ts.",
);

// File-count truncation (10 distinct files, maxFiles default 8 → "+2 more").
const many = Array.from({ length: 10 }, (_, i) => edit(`/x/f${i}.ts`));
eq(
  "rollup-truncate",
  formatRollup({ started_at: null, ended_at: null, branch: null, commit_sha: null }, many),
  "Auto session rollup — 10 edits across 10 files: f0.ts, f1.ts, f2.ts, f3.ts, f4.ts, f5.ts, f6.ts, f7.ts +2 more.",
);

// Edits with no file_path still count, but contribute no file names.
eq(
  "rollup-null-paths",
  formatRollup({ started_at: null, ended_at: null, branch: null, commit_sha: null }, [edit(null), edit(null)]),
  "Auto session rollup — 2 edits across 0 files.",
);

// formatCompactHandoff — prefixes the rollup body with a compaction marker (+ trigger).
eq("compact-null-body", formatCompactHandoff(null, "auto"), null);
eq("compact-empty-body", formatCompactHandoff("", "auto"), null);
eq(
  "compact-auto",
  formatCompactHandoff("Auto session rollup — 1 edit across 1 file: q.ts.", "auto"),
  "Context compacted (auto). Auto session rollup — 1 edit across 1 file: q.ts.",
);
eq(
  "compact-manual",
  formatCompactHandoff("Auto session rollup — 2 edits across 1 file: a.ts.", "manual"),
  "Context compacted (manual). Auto session rollup — 2 edits across 1 file: a.ts.",
);
// Unknown / missing trigger → no parenthetical, still a valid handoff.
eq(
  "compact-unknown-trigger",
  formatCompactHandoff("Auto session rollup — 1 edit across 1 file: q.ts.", "weird"),
  "Context compacted. Auto session rollup — 1 edit across 1 file: q.ts.",
);
eq(
  "compact-null-trigger",
  formatCompactHandoff("Auto session rollup — 1 edit across 1 file: q.ts.", null),
  "Context compacted. Auto session rollup — 1 edit across 1 file: q.ts.",
);
// Integration: formatRollup → formatCompactHandoff produces the stored body shape.
eq(
  "compact-from-rollup",
  formatCompactHandoff(formatRollup(sess, [edit("/x/a.ts"), edit("/x/b.ts")]), "auto"),
  "Context compacted (auto). Auto session rollup (branch main, @abc1234, ~25m) — 2 edits across 2 files: a.ts, b.ts.",
);

// liveEdits — drop edits whose file no longer exists; keep extant files and null paths.
const keep = new Set(["/x/a.ts", "/x/c.ts"]);
const exists = (p: string) => keep.has(p);
const mixed: EditRow[] = [edit("/x/a.ts"), edit("/x/gone.ts"), edit(null), edit("/x/c.ts")];
const live = liveEdits(mixed, exists);
eq("live-count", String(live.length), "3"); // a.ts, null, c.ts (gone.ts dropped)
eq(
  "live-paths",
  live.map((e) => e.file_path).join(","),
  "/x/a.ts,,/x/c.ts",
);
eq("live-none-exist", String(liveEdits([edit("/x/gone.ts")], exists).length), "0");

// Integration: liveEdits → formatRollup drops the deleted file from the summary.
eq(
  "live-then-format",
  formatRollup(
    { started_at: null, ended_at: null, branch: null, commit_sha: null },
    liveEdits([edit("/x/a.ts"), edit("/x/gone.ts")], exists),
  ),
  "Auto session rollup — 1 edit across 1 file: a.ts.",
);

// --- pruneOldRollups (DB-touching, tmp SQLite — like mcp/handlers.test.ts).
const root = mkdtempSync(join(tmpdir(), "session-journal-rollup-test-"));
try {
  const db = openDb(join(root, "state.db"));
  try {
    const REPO_A = "owner/a";
    const REPO_B = "owner/b";
    const insertNote = (repo: string | null, key: string | null, body: string, ts: string): number => {
      const info = db
        .prepare("INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)")
        .run(null, repo, key, body, ts);
      return Number(info.lastInsertRowid);
    };
    const setPin = (id: number, pinned: 0 | 1): void => {
      db.prepare("UPDATE notes SET pinned = ? WHERE id = ?").run(pinned, id);
    };
    const rollupIdsFor = (repo: string | null): number[] => {
      const sql =
        repo === null
          ? "SELECT id FROM notes WHERE key = 'session-rollup' AND repo IS NULL ORDER BY id ASC"
          : "SELECT id FROM notes WHERE key = 'session-rollup' AND repo = ? ORDER BY id ASC";
      const rows = (repo === null ? db.prepare(sql).all() : db.prepare(sql).all(repo)) as Array<{
        id: number;
      }>;
      return rows.map((r) => r.id);
    };

    // 7 rollups in REPO_A (ts only ordered for realism; pruning uses id desc).
    const aIds = [
      insertNote(REPO_A, "session-rollup", "a-1", "2026-05-26T00:00:01.000Z"),
      insertNote(REPO_A, "session-rollup", "a-2", "2026-05-26T00:00:02.000Z"),
      insertNote(REPO_A, "session-rollup", "a-3", "2026-05-26T00:00:03.000Z"),
      insertNote(REPO_A, "session-rollup", "a-4", "2026-05-26T00:00:04.000Z"),
      insertNote(REPO_A, "session-rollup", "a-5", "2026-05-26T00:00:05.000Z"),
      insertNote(REPO_A, "session-rollup", "a-6", "2026-05-26T00:00:06.000Z"),
      insertNote(REPO_A, "session-rollup", "a-7", "2026-05-26T00:00:07.000Z"),
    ];
    // 2 rollups in REPO_B (other repo — must be untouched by pruning REPO_A).
    const bIds = [
      insertNote(REPO_B, "session-rollup", "b-1", "2026-05-26T00:01:01.000Z"),
      insertNote(REPO_B, "session-rollup", "b-2", "2026-05-26T00:01:02.000Z"),
    ];
    // Non-rollup notes in REPO_A — must be untouched.
    const nonRollupId = insertNote(REPO_A, "checkpoint", "a checkpoint", "2026-05-26T00:00:08.000Z");
    const keylessId = insertNote(REPO_A, null, "a keyless note", "2026-05-26T00:00:09.000Z");

    // Default retention keeps 5: drops the 2 oldest (a-1, a-2).
    const deletedA = pruneOldRollups(db, REPO_A);
    eq("prune deletes count", String(deletedA), "2");
    eq("prune default retention constant", String(ROLLUP_RETENTION), "5");

    const afterA = rollupIdsFor(REPO_A);
    eq("prune keeps last 5 by id", afterA.join(","), aIds.slice(2).join(","));

    // REPO_B untouched.
    eq("prune does not cross repos", rollupIdsFor(REPO_B).join(","), bIds.join(","));

    // Non-rollup notes in REPO_A untouched.
    const checkpointStill = (
      db.prepare("SELECT id FROM notes WHERE id = ?").get(nonRollupId) as { id: number } | undefined
    )?.id;
    eq("prune leaves checkpoint", String(checkpointStill), String(nonRollupId));
    const keylessStill = (
      db.prepare("SELECT id FROM notes WHERE id = ?").get(keylessId) as { id: number } | undefined
    )?.id;
    eq("prune leaves keyless note", String(keylessStill), String(keylessId));

    // Pinned rollups are preserved even when older than the retention window.
    const pinned = insertNote(REPO_A, "session-rollup", "a-pinned-old", "2025-01-01T00:00:00.000Z");
    setPin(pinned, 1);
    // Now there are 5 unpinned + 1 pinned = 6 rollups. keep=2 should drop 3 unpinned, leave pinned.
    const deletedA2 = pruneOldRollups(db, REPO_A, 2);
    eq("prune ignores pinned when counting kept", String(deletedA2), "3");
    const pinnedStill = (
      db.prepare("SELECT id FROM notes WHERE id = ?").get(pinned) as { id: number } | undefined
    )?.id;
    eq("prune preserves pinned rollup", String(pinnedStill), String(pinned));

    // No-repo (null) scope: pruning a null-repo session must not touch named-repo rollups.
    const nullIds = [
      insertNote(null, "session-rollup", "n-1", "2026-05-27T00:00:01.000Z"),
      insertNote(null, "session-rollup", "n-2", "2026-05-27T00:00:02.000Z"),
      insertNote(null, "session-rollup", "n-3", "2026-05-27T00:00:03.000Z"),
    ];
    const deletedNull = pruneOldRollups(db, null, 1);
    eq("prune null-scope deletes count", String(deletedNull), "2");
    const remainingNull = rollupIdsFor(null);
    eq("prune null-scope keeps newest", remainingNull.join(","), String(nullIds[2]));
    // REPO_B still untouched after null-scope prune.
    eq("prune null-scope does not touch repo B", rollupIdsFor(REPO_B).join(","), bIds.join(","));

    // keep=0 removes all unpinned for the scope.
    const deletedZero = pruneOldRollups(db, REPO_B, 0);
    eq("prune keep=0 deletes all unpinned", String(deletedZero), "2");
    eq("prune keep=0 leaves nothing unpinned", rollupIdsFor(REPO_B).join(","), "");

    // Negative keep is a no-op (defensive).
    const deletedNeg = pruneOldRollups(db, REPO_A, -1);
    eq("prune negative keep is no-op", String(deletedNeg), "0");

    // --- pruneOldNotesByKey with the v7 compact-handoff key (key-scoped, repo-scoped).
    eq("compact retention constant", String(COMPACT_HANDOFF_RETENTION), "3");
    eq("compact key constant", COMPACT_HANDOFF_KEY, "compact-handoff");

    const notesByKey = (repo: string | null, key: string): number[] => {
      const rows = db
        .prepare("SELECT id FROM notes WHERE key = ? AND repo IS NOT DISTINCT FROM ? ORDER BY id ASC")
        .all(key, repo) as Array<{ id: number }>;
      return rows.map((r) => r.id);
    };

    // 5 compact-handoffs in REPO_A; keep 3 → drop the 2 oldest.
    const chIds = [
      insertNote(REPO_A, COMPACT_HANDOFF_KEY, "ch-1", "2026-05-28T00:00:01.000Z"),
      insertNote(REPO_A, COMPACT_HANDOFF_KEY, "ch-2", "2026-05-28T00:00:02.000Z"),
      insertNote(REPO_A, COMPACT_HANDOFF_KEY, "ch-3", "2026-05-28T00:00:03.000Z"),
      insertNote(REPO_A, COMPACT_HANDOFF_KEY, "ch-4", "2026-05-28T00:00:04.000Z"),
      insertNote(REPO_A, COMPACT_HANDOFF_KEY, "ch-5", "2026-05-28T00:00:05.000Z"),
    ];
    // A session-rollup in REPO_A must be untouched by a compact-handoff prune (key isolation).
    const survivingRollup = insertNote(REPO_A, "session-rollup", "still-here", "2026-05-28T00:00:06.000Z");

    const deletedCh = pruneOldNotesByKey(db, COMPACT_HANDOFF_KEY, REPO_A, COMPACT_HANDOFF_RETENTION);
    eq("compact prune deletes count", String(deletedCh), "2");
    eq("compact prune keeps newest 3", notesByKey(REPO_A, COMPACT_HANDOFF_KEY).join(","), chIds.slice(2).join(","));
    eq(
      "compact prune leaves other-key notes",
      String((db.prepare("SELECT id FROM notes WHERE id = ?").get(survivingRollup) as { id: number } | undefined)?.id),
      String(survivingRollup),
    );

    // Pinned compact-handoff preserved beyond the window.
    const chPinned = insertNote(REPO_A, COMPACT_HANDOFF_KEY, "ch-pinned-old", "2025-01-01T00:00:00.000Z");
    setPin(chPinned, 1);
    const deletedCh2 = pruneOldNotesByKey(db, COMPACT_HANDOFF_KEY, REPO_A, 1);
    // 3 unpinned remained + 1 pinned; keep=1 drops 2 unpinned, preserves pinned.
    eq("compact prune ignores pinned when counting", String(deletedCh2), "2");
    eq(
      "compact prune preserves pinned",
      String((db.prepare("SELECT id FROM notes WHERE id = ?").get(chPinned) as { id: number } | undefined)?.id),
      String(chPinned),
    );
  } finally {
    db.close();
  }
} finally {
  if (existsSync(root)) rmSync(root, { recursive: true, force: true });
}

if (failed > 0) {
  console.error(`\nrollup: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("rollup: all assertions pass");
