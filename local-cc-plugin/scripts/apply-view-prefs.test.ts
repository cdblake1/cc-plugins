// Unit tests for the pure parts of apply-view-prefs (merge + parse). The filesystem write
// in main() is thin I/O around computeUpdate and not exercised here. Run via `npm test`.
import { applyPrefs, computeUpdate } from "./apply-view-prefs.ts";

let failed = 0;
function eq(name: string, got: unknown, want: unknown): void {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) {
    failed++;
    console.error(`FAIL ${name}: got ${g} want ${w}`);
  }
}

// applyPrefs: sets absent keys, preserves others
{
  const { next, changed } = applyPrefs({ theme: "dark" }, { viewMode: "focus", outputStyle: "Concise" });
  eq("set-both/changed", changed, true);
  eq("set-both/next", next, { theme: "dark", viewMode: "focus", outputStyle: "Concise" });
}

// applyPrefs: preserves an existing unrelated key while only updating viewMode
{
  const { next, changed } = applyPrefs(
    { skipDangerousModePermissionPrompt: true, viewMode: "verbose" },
    { viewMode: "focus" },
  );
  eq("update-one/changed", changed, true);
  eq("update-one/next", next, { skipDangerousModePermissionPrompt: true, viewMode: "focus" });
}

// applyPrefs: no-op when the value already matches
{
  const { next, changed } = applyPrefs({ viewMode: "focus" }, { viewMode: "focus" });
  eq("noop/changed", changed, false);
  eq("noop/next", next, { viewMode: "focus" });
}

// applyPrefs: invalid values are ignored (no change)
{
  const { changed } = applyPrefs({}, { viewMode: "loud", outputStyle: "Yelling" });
  eq("invalid/ignored", changed, false);
}

// applyPrefs: empty prefs change nothing
eq("empty-prefs", applyPrefs({ a: 1 }, {}).changed, false);

// computeUpdate: absent file (null raw) -> sets keys on a fresh object
{
  const { text, changed, error } = computeUpdate(null, { viewMode: "focus" });
  eq("absent/error", error, null);
  eq("absent/changed", changed, true);
  eq("absent/text", text, '{\n  "viewMode": "focus"\n}\n');
}

// computeUpdate: empty file behaves like absent
eq("empty-file", computeUpdate("   ", { viewMode: "default" }).changed, true);

// computeUpdate: preserves existing keys and emits pretty JSON
{
  const raw = '{\n  "theme": "dark"\n}\n';
  const { text, error } = computeUpdate(raw, { viewMode: "focus" });
  eq("preserve/error", error, null);
  eq("preserve/text", text, '{\n  "theme": "dark",\n  "viewMode": "focus"\n}\n');
}

// computeUpdate: already-matching settings -> no write (text null, changed false)
{
  const { text, changed } = computeUpdate('{"viewMode":"focus"}', { viewMode: "focus" });
  eq("match/changed", changed, false);
  eq("match/text", text, null);
}

// computeUpdate: malformed JSON -> error set, no text (caller must not write)
{
  const { text, error } = computeUpdate("{ not json", { viewMode: "focus" });
  eq("malformed/text-null", text, null);
  eq("malformed/has-error", typeof error === "string" && error.length > 0, true);
}

// computeUpdate: non-object JSON (array) -> error, no write
{
  const { text, error } = computeUpdate("[1,2,3]", { viewMode: "focus" });
  eq("array/text-null", text, null);
  eq("array/has-error", typeof error === "string" && error.length > 0, true);
}

if (failed > 0) {
  console.error(`\napply-view-prefs: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("apply-view-prefs: all assertions pass");
