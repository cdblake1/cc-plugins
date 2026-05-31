// Unit tests for transcript / context-budget helpers (v7). Pure functions plus the bounded IO
// readers against tmp files. Run via `npm test`.

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  parseUsageLine,
  liveContextTokens,
  formatBudget,
  parseBudgetConfig,
  readLatestUsage,
  latestTranscriptPath,
  transcriptDirFor,
  DEFAULT_CONTEXT_WINDOW,
  type ContextUsage,
} from "./transcript.ts";

let failed = 0;
function eq(name: string, got: unknown, want: unknown): void {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) {
    failed++;
    console.error(`FAIL ${name}: got ${g} want ${w}`);
  }
}

// --- parseUsageLine (pure)
const usageObj = (u: Record<string, unknown>) => JSON.stringify({ type: "assistant", message: { usage: u } });

eq("parse empty", parseUsageLine(""), null);
eq("parse malformed", parseUsageLine("{not json"), null);
eq("parse non-object", parseUsageLine("42"), null);
eq("parse user line", parseUsageLine(JSON.stringify({ type: "user", message: { content: "hi" } })), null);
eq("parse assistant no usage", parseUsageLine(JSON.stringify({ type: "assistant", message: {} })), null);
eq(
  "parse full usage",
  parseUsageLine(
    usageObj({ input_tokens: 147, cache_read_input_tokens: 65728, cache_creation_input_tokens: 478, output_tokens: 76 }),
  ),
  { input: 147, cacheRead: 65728, cacheCreate: 478, output: 76 },
);
eq(
  "parse missing fields → zeros",
  parseUsageLine(usageObj({ input_tokens: 10 })),
  { input: 10, cacheRead: 0, cacheCreate: 0, output: 0 },
);
eq("parse usage all-absent → null", parseUsageLine(usageObj({ service_tier: "standard" })), null);

// --- liveContextTokens (pure): output excluded
eq(
  "live tokens sums input side, excludes output",
  String(liveContextTokens({ input: 147, cacheRead: 65728, cacheCreate: 478, output: 999 } as ContextUsage)),
  String(147 + 65728 + 478),
);

// --- formatBudget (pure)
eq("budget pct + label", formatBudget(66353, 200000), {
  tokens: 66353,
  windowTokens: 200000,
  pct: 33,
  tier: "ok",
  label: "~66k / 200k tokens (33%)",
});
eq("budget tier warn at 70%", formatBudget(140000, 200000).tier, "warn");
eq("budget tier high at 90%", formatBudget(180000, 200000).tier, "high");
eq("budget tier ok just under warn", formatBudget(138000, 200000).tier, "ok"); // 69%
eq("budget sub-1k label", formatBudget(950, 200000).label, "~950 / 200k tokens (0%)");
eq("budget zero window → default", formatBudget(100000, 0).windowTokens, DEFAULT_CONTEXT_WINDOW);

// --- parseBudgetConfig (pure)
eq("config unset → null", parseBudgetConfig({}), null);
eq("config blank → null", parseBudgetConfig({ CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "  " }), null);
eq("config invalid zero → null", parseBudgetConfig({ CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "0" }), null);
eq("config invalid >100 → null", parseBudgetConfig({ CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "150" }), null);
eq("config NaN → null", parseBudgetConfig({ CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "lots" }), null);
eq(
  "config valid pct, default window",
  parseBudgetConfig({ CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "75" }),
  { warnPct: 75, window: DEFAULT_CONTEXT_WINDOW },
);
eq(
  "config valid pct + custom window",
  parseBudgetConfig({
    CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "80",
    CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS: "1000000",
  }),
  { warnPct: 80, window: 1000000 },
);
eq(
  "config bad window → default",
  parseBudgetConfig({
    CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT: "80",
    CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS: "-5",
  }),
  { warnPct: 80, window: DEFAULT_CONTEXT_WINDOW },
);

// --- transcriptDirFor (pure-ish): slug = non-alphanumeric → '-'
eq(
  "transcript dir slug",
  transcriptDirFor("/Users/x/repos/cc-plugins", "/cfg"),
  join("/cfg", "projects", "-Users-x-repos-cc-plugins"),
);

// --- readLatestUsage + latestTranscriptPath (IO against tmp files)
const root = mkdtempSync(join(tmpdir(), "session-journal-transcript-test-"));
try {
  // Missing file → null.
  eq("readLatestUsage missing file", readLatestUsage(join(root, "nope.jsonl")), null);

  // Multiple assistant entries → last one wins.
  const tPath = join(root, "t.jsonl");
  writeFileSync(
    tPath,
    [
      usageObj({ input_tokens: 1, cache_read_input_tokens: 10, cache_creation_input_tokens: 0, output_tokens: 5 }),
      JSON.stringify({ type: "user", message: { content: "noise" } }),
      usageObj({ input_tokens: 2, cache_read_input_tokens: 30000, cache_creation_input_tokens: 100, output_tokens: 9 }),
      JSON.stringify({ type: "user", message: { content: "trailing non-usage line" } }),
    ].join("\n") + "\n",
  );
  eq("readLatestUsage last wins (ignores trailing user line)", readLatestUsage(tPath), {
    input: 2,
    cacheRead: 30000,
    cacheCreate: 100,
    output: 9,
  });

  // Tail miss → full-scan fallback: usage line at the start, then padding longer than tailBytes.
  const fbPath = join(root, "fallback.jsonl");
  const pad = JSON.stringify({ type: "user", message: { content: "x".repeat(2000) } });
  writeFileSync(
    fbPath,
    [usageObj({ input_tokens: 123, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, output_tokens: 0 }), pad].join("\n") + "\n",
  );
  eq(
    "readLatestUsage tail-miss falls back to full scan",
    readLatestUsage(fbPath, 64),
    { input: 123, cacheRead: 0, cacheCreate: 0, output: 0 },
  );

  // latestTranscriptPath: pick newest by mtime within the project's slug dir.
  const cfg = join(root, "cfg");
  const projDir = "/fake/proj";
  const slugDir = transcriptDirFor(projDir, cfg);
  mkdirSync(slugDir, { recursive: true });
  const older = join(slugDir, "older.jsonl");
  const newer = join(slugDir, "newer.jsonl");
  writeFileSync(older, usageObj({ input_tokens: 1 }) + "\n");
  writeFileSync(newer, usageObj({ input_tokens: 2 }) + "\n");
  utimesSync(older, 1000, 1000);
  utimesSync(newer, 2000, 2000);
  eq("latestTranscriptPath picks newest", latestTranscriptPath(projDir, cfg), newer);

  // Missing project dir → null.
  eq("latestTranscriptPath missing dir", latestTranscriptPath("/no/such/proj", cfg), null);
} finally {
  if (existsSync(root)) rmSync(root, { recursive: true, force: true });
}

if (failed > 0) {
  console.error(`\ntranscript: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("transcript: all assertions pass");
