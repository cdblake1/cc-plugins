// Unit tests for the pure rollup formatting (v5 auto-capture). Run via `npm test`.
import { formatDuration, baseName, formatRollup, type EditRow } from "./rollup.ts";

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

if (failed > 0) {
  console.error(`\nrollup: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("rollup: all assertions pass");
