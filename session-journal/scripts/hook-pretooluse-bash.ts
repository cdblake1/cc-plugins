// PreToolUse hook (matcher Bash): the guardrail. Hard policy, so it runs synchronously
// and HARD-BLOCKS with exit 2 (per the hook safety rules — exit 1 would be non-blocking).
// Ambiguous-but-risky commands return an "ask" permission decision instead of denying.
// Every decision is logged to the guardrail table.
//
// Decision mapping:
//   deny  -> write reason to stderr, exit 2  (blocks the tool call)
//   ask   -> emit PreToolUse permissionDecision=ask JSON, exit 0
//   allow -> exit 0 silently

import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";

export type Decision = { decision: "allow" | "ask" | "deny"; reason: string };

const DANGEROUS_RM_TARGETS = new Set([
  "/",
  "/*",
  "~",
  "~/",
  "..",
  "../",
  "$HOME",
  "${HOME}",
]);

/** Crude whitespace tokenization — good enough for guardrail heuristics. */
function rmHitsDangerousTarget(command: string): boolean {
  const tokens = command.split(/\s+/);
  const rmIdx = tokens.findIndex((t) => t === "rm" || t.endsWith("/rm"));
  if (rmIdx === -1) return false;
  for (let i = rmIdx + 1; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.startsWith("-")) continue; // a flag, not a target
    const normalized = t.replace(/\/+$/, "") || "/"; // strip trailing slashes (keep "/")
    if (DANGEROUS_RM_TARGETS.has(t) || DANGEROUS_RM_TARGETS.has(normalized)) return true;
  }
  return false;
}

/** Pure policy evaluation, exported for unit testing. */
export function evaluate(commandRaw: string): Decision {
  const c = (commandRaw ?? "").trim();
  if (!c) return { decision: "allow", reason: "" };

  // DENY: pipe a remote download straight into a shell (remote code execution).
  if (/\b(curl|wget|fetch)\b[^\n|]*\|\s*(sudo\s+)?\S*\b(sh|bash|zsh|dash)\b/i.test(c)) {
    return {
      decision: "deny",
      reason: "Piping downloaded content into a shell (remote code execution) is blocked.",
    };
  }

  // DENY: recursive + force rm targeting /, ~, $HOME, or ..
  const rmRecursive = /\brm\b[^|&;]*?(?:\s-[a-z]*r[a-z]*|\s--recursive)\b/i.test(c);
  const rmForce = /\brm\b[^|&;]*?(?:\s-[a-z]*f[a-z]*|\s--force)\b/i.test(c);
  if (rmRecursive && rmForce && rmHitsDangerousTarget(c)) {
    return {
      decision: "deny",
      reason: "Recursive force-remove targeting /, ~, $HOME, or .. is blocked.",
    };
  }

  const isGitPush = /\bgit\s+push\b/i.test(c);
  const hasForce = /(\s--force\b|\s-f\b)/i.test(c) && !/--force-with-lease\b/i.test(c);

  // DENY: force-push to a protected branch.
  if (isGitPush && hasForce && /\b(main|master)\b/i.test(c)) {
    return {
      decision: "deny",
      reason: "Force-pushing to a protected branch (main/master) is blocked.",
    };
  }

  // ASK: any other force-push (incl. --force-with-lease).
  if (isGitPush && (/(\s--force\b|\s-f\b)/i.test(c) || /--force-with-lease\b/i.test(c))) {
    return { decision: "ask", reason: "Force-push detected; confirm the target branch is safe." };
  }

  // ASK: elevated privileges.
  if (/(^|[\s|&;])sudo\s/i.test(c)) {
    return { decision: "ask", reason: "Command uses sudo (elevated privileges)." };
  }

  return { decision: "allow", reason: "" };
}

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

// Only run the event loop when executed as a hook (not when imported by tests).
if (process.env.SESSION_JOURNAL_TEST !== "1") {
  const input = await readHookInput<{
    session_id?: string;
    tool_name?: string;
    tool_input?: { command?: string };
  }>();

  const command = input.tool_input?.command ?? "";
  const d = evaluate(command);
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
}
