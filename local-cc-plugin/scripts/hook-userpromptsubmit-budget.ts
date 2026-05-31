// UserPromptSubmit hook (v7 context-efficiency): once per user turn, before Claude responds,
// surface a one-line context-budget nudge when occupancy crosses the configured threshold — the
// natural moment to decide to /checkpoint then /compact (now safe, thanks to the PreCompact
// handoff) and keep context lean. Stdout on UserPromptSubmit is injected as context.
//
// Opt-in: disabled unless userConfig `context_budget_warn_pct` is set (exported as
// CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT). Zero impact by default, mirroring the Stop
// hygiene gate. Best-effort and non-blocking — always exits 0, never gates a prompt.

import { readHookInput } from "./hooklib.ts";
import { parseBudgetConfig, readLatestUsage, liveContextTokens, formatBudget } from "./transcript.ts";

try {
  const cfg = parseBudgetConfig(process.env);
  if (cfg) {
    const input = await readHookInput<{ transcript_path?: string }>();
    if (input.transcript_path) {
      const usage = readLatestUsage(input.transcript_path);
      if (usage) {
        const b = formatBudget(liveContextTokens(usage), cfg.window);
        if (b.pct >= cfg.warnPct) {
          process.stdout.write(
            `[session-journal] Context budget: ${b.label}. ` +
              `Consider /checkpoint then /compact (or /clear) to keep context lean — ` +
              `the PreCompact handoff preserves what's in flight.\n`,
          );
        }
      }
    }
  }
} catch {
  // Never let the budget nudge disrupt a prompt.
}
process.exit(0);
