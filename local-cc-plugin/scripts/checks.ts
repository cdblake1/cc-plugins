// Dev-hygiene check runner (v2). Commands come from userConfig, exported to this
// subprocess as CLAUDE_PLUGIN_OPTION_<KEY>. Everything here is opt-in: if no command is
// configured, no check runs.

import { execSync } from "node:child_process";

export type CheckKind = "format" | "lint" | "test";
export type CheckSpec = { kind: CheckKind; command: string };
export type CheckResult = CheckSpec & { ok: boolean; output: string };

// userConfig keys -> exported env var names.
const ENV_KEYS: Record<CheckKind, string> = {
  format: "CLAUDE_PLUGIN_OPTION_FORMAT_COMMAND",
  lint: "CLAUDE_PLUGIN_OPTION_LINT_COMMAND",
  test: "CLAUDE_PLUGIN_OPTION_TEST_COMMAND",
};

/** Pure: which checks are configured, in run order (format → lint → test). */
export function configuredChecks(env: Record<string, string | undefined>): CheckSpec[] {
  const order: CheckKind[] = ["format", "lint", "test"];
  const specs: CheckSpec[] = [];
  for (const kind of order) {
    const command = (env[ENV_KEYS[kind]] ?? "").trim();
    if (command) specs.push({ kind, command });
  }
  return specs;
}

/** Run one check command in `cwd`. Never throws; non-zero exit → ok:false. */
export function runCheck(spec: CheckSpec, cwd: string, timeoutMs = 120_000): CheckResult {
  try {
    const output = execSync(spec.command, {
      cwd,
      encoding: "utf8",
      timeout: timeoutMs,
      maxBuffer: 10 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { ...spec, ok: true, output: tail(output) };
  } catch (err) {
    const e = err as { stdout?: unknown; stderr?: unknown; message?: string };
    const combined = [e.stdout, e.stderr]
      .map((s) => (s == null ? "" : String(s)))
      .join("\n")
      .trim();
    return { ...spec, ok: false, output: tail(combined || e.message || "command failed") };
  }
}

/** Keep only the last ~4000 chars so the store and the gate message stay small. */
function tail(s: string): string {
  const str = String(s);
  return str.length > 4000 ? str.slice(-4000) : str;
}
