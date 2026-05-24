// Unit tests for the dev-hygiene check runner. Run via `npm test`.
import { configuredChecks, runCheck } from "./checks.ts";

let failed = 0;
function check(name: string, cond: boolean): void {
  if (!cond) {
    failed++;
    console.error(`FAIL  ${name}`);
  }
}

// configuredChecks: only non-empty commands, in order format -> lint -> test.
const none = configuredChecks({});
check("no env -> no checks", none.length === 0);

const some = configuredChecks({
  CLAUDE_PLUGIN_OPTION_TEST_COMMAND: "echo t",
  CLAUDE_PLUGIN_OPTION_FORMAT_COMMAND: "echo f",
  CLAUDE_PLUGIN_OPTION_LINT_COMMAND: "   ", // whitespace-only -> ignored
});
check("ignores whitespace-only command", some.length === 2);
check("order is format then test", some[0].kind === "format" && some[1].kind === "test");

// runCheck: exit 0 -> ok, non-zero -> not ok, output captured.
// Use `node -e` so commands parse identically on cmd.exe and POSIX shells.
const ok = runCheck(
  { kind: "lint", command: `node -e "console.log('hello-lint')"` },
  process.cwd(),
);
check("passing command ok=true", ok.ok === true);
check("passing command captures stdout", ok.output.includes("hello-lint"));

const bad = runCheck(
  { kind: "test", command: `node -e "console.log('boom-out'); process.exit(3)"` },
  process.cwd(),
);
check("failing command ok=false", bad.ok === false);
check("failing command captures output", bad.output.includes("boom-out"));

if (failed > 0) {
  console.error(`\nchecks: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("checks: all assertions pass");
