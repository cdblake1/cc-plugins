// PreToolUse hook (matcher Bash): the guardrail. Hard policy, so it runs synchronously
// and HARD-BLOCKS with exit 2 (per the hook safety rules — exit 1 would be non-blocking).
// Ambiguous-but-risky commands return an "ask" permission decision instead of denying.
// Every decision is logged to the guardrail table.
//
// Policy lives in ./guardrail-policy.ts (pure, unit-tested); this file is just the I/O.
//
// Decision mapping:
//   deny  -> write reason to stderr, exit 2  (blocks the tool call)
//   ask   -> emit PreToolUse permissionDecision=ask JSON, exit 0
//   allow -> exit 0 silently

import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { evaluate, type Decision } from "./guardrail-policy.ts";
import { defaultBranch } from "./gitctx.ts";

function logDecision(sessionId: string | null, command: string, d: Decision): void {
  try {
    const db = openDb();
    try {
      db.prepare(
        "INSERT INTO guardrail (session_id, command, decision, reason, ts) VALUES (?, ?, ?, ?, ?)",
      ).run(sessionId, command, d.decision, d.reason || null, now());
    } finally {
      db.close();
    }
  } catch (err) {
    // Logging must never weaken the guardrail; surface to stderr and continue.
    console.error("session-journal guardrail log:", (err as Error).message);
  }
}

const input = await readHookInput<{
  session_id?: string;
  cwd?: string;
  tool_name?: string;
  tool_input?: { command?: string };
}>();

const command = input.tool_input?.command ?? "";
// Protect the repo's real default branch (e.g. "develop"), plus main/master as a safety net.
const def = defaultBranch(input.cwd ?? process.cwd());
const protectedBranches = [...new Set([def, "main", "master"].filter(Boolean) as string[])];
const d = evaluate(command, protectedBranches);
logDecision(input.session_id ?? null, command, d);

if (d.decision === "deny") {
  console.error(`BLOCKED by session-journal guardrail: ${d.reason}`);
  process.exit(2);
}
if (d.decision === "ask") {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "ask",
        permissionDecisionReason: d.reason,
      },
    }),
  );
}
process.exit(0);
