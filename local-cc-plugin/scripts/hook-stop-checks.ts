// Stop hook (v2 dev-hygiene gate): when Claude finishes, run the configured
// format/lint/test commands. If any fail, BLOCK with exit 2 and feed the failures back so
// Claude fixes them before the turn ends. Logs every run to the `checks` table.
//
// Opt-in: if no command is configured (userConfig), this is a no-op.
// Gated on stop_hook_active to avoid an infinite stop/continue loop (the gate fires once
// per turn-chain, giving the model one shot to fix).

import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";
import { configuredChecks, runCheck, type CheckResult } from "./checks.ts";

const input = await readHookInput<{
  session_id?: string;
  cwd?: string;
  stop_hook_active?: boolean;
}>();

if (input.stop_hook_active) process.exit(0); // already in a continue loop — don't re-gate

const specs = configuredChecks(process.env);
if (specs.length === 0) process.exit(0); // nothing configured → opt-out by default

const cwd = input.cwd ?? process.cwd();
const results: CheckResult[] = specs.map((s) => runCheck(s, cwd));

try {
  const db = openDb();
  try {
    const stmt = db.prepare(
      "INSERT INTO checks (session_id, kind, command, ok, output, ts) VALUES (?, ?, ?, ?, ?, ?)",
    );
    for (const r of results) {
      stmt.run(input.session_id ?? null, r.kind, r.command, r.ok ? 1 : 0, r.output || null, now());
    }
  } finally {
    db.close();
  }
} catch (err) {
  console.error("session-journal checks log:", (err as Error).message);
}

const failed = results.filter((r) => !r.ok);
if (failed.length > 0) {
  const detail = failed.map((r) => `✗ ${r.kind} (\`${r.command}\`):\n${r.output}`).join("\n\n");
  console.error(
    `Dev-hygiene gate: ${failed.length} check(s) failed — fix before finishing.\n\n${detail}`,
  );
  process.exit(2); // block the stop
}
process.exit(0);
