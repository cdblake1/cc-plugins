// Apply Claude Code view-verbosity preferences (viewMode, outputStyle) to the user's
// settings.json. Backs the `/init` command. Non-destructive: preserves every other key.
// Idempotent, and bails without writing if the existing settings.json is malformed.
// Uses only built-in modules — no node_modules, NOT part of the MCP bundle.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

export const VIEW_MODES = ["focus", "default", "verbose"] as const;
// Built-in output styles. "Default" is the standard style; custom styles are out of scope here.
export const OUTPUT_STYLES = ["Concise", "Default", "Explanatory", "Proactive"] as const;

export type Prefs = { viewMode?: string; outputStyle?: string };

// Pure: merge desired prefs into an existing settings object. Sets a key only when the
// requested value is valid and differs from what's there; preserves all other keys.
export function applyPrefs(
  existing: Record<string, unknown>,
  prefs: Prefs,
): { next: Record<string, unknown>; changed: boolean } {
  const next = { ...existing };
  let changed = false;
  if (prefs.viewMode && (VIEW_MODES as readonly string[]).includes(prefs.viewMode)) {
    if (next.viewMode !== prefs.viewMode) {
      next.viewMode = prefs.viewMode;
      changed = true;
    }
  }
  if (prefs.outputStyle && (OUTPUT_STYLES as readonly string[]).includes(prefs.outputStyle)) {
    if (next.outputStyle !== prefs.outputStyle) {
      next.outputStyle = prefs.outputStyle;
      changed = true;
    }
  }
  return { next, changed };
}

// Pure: given the raw contents of settings.json (or null if the file is absent), produce the
// text to write back. `error` is set (and `text` null) when the file exists but isn't a JSON
// object — callers must NOT write in that case. `text` is null when nothing changed.
export function computeUpdate(
  raw: string | null,
  prefs: Prefs,
): { text: string | null; changed: boolean; error: string | null } {
  let existing: Record<string, unknown> = {};
  const trimmed = (raw ?? "").trim();
  if (trimmed) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch (err) {
      return { text: null, changed: false, error: `invalid JSON (${(err as Error).message})` };
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { text: null, changed: false, error: "settings.json is not a JSON object" };
    }
    existing = parsed as Record<string, unknown>;
  }
  const { next, changed } = applyPrefs(existing, prefs);
  return { text: changed ? JSON.stringify(next, null, 2) + "\n" : null, changed, error: null };
}

// User settings live at $CLAUDE_CONFIG_DIR/settings.json, defaulting to ~/.claude/settings.json.
export function settingsPath(): string {
  const base = process.env.CLAUDE_CONFIG_DIR?.trim() || join(homedir(), ".claude");
  return join(base, "settings.json");
}

function parseArgs(argv: string[]): Prefs {
  const prefs: Prefs = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--view-mode") prefs.viewMode = argv[++i];
    else if (a.startsWith("--view-mode=")) prefs.viewMode = a.slice("--view-mode=".length);
    else if (a === "--output-style") prefs.outputStyle = argv[++i];
    else if (a.startsWith("--output-style=")) prefs.outputStyle = a.slice("--output-style=".length);
  }
  return prefs;
}

function main(): void {
  const prefs = parseArgs(process.argv.slice(2));
  if (!prefs.viewMode && !prefs.outputStyle) {
    console.log("apply-view-prefs: nothing to do (pass --view-mode and/or --output-style).");
    return;
  }
  const path = settingsPath();
  const raw = existsSync(path) ? readFileSync(path, "utf8") : null;
  const { text, changed, error } = computeUpdate(raw, prefs);
  if (error) {
    console.error(`apply-view-prefs: ${path} — ${error}; aborting (settings left untouched).`);
    process.exitCode = 1;
    return;
  }
  if (!changed || text === null) {
    console.log("apply-view-prefs: settings already match; no change.");
    return;
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, "utf8");
  const set = [
    prefs.viewMode ? `viewMode=${prefs.viewMode}` : null,
    prefs.outputStyle ? `outputStyle=${prefs.outputStyle}` : null,
  ]
    .filter(Boolean)
    .join(", ");
  console.log(`apply-view-prefs: updated ${path} (${set}).`);
}

// Run only when invoked directly, not when imported by the test.
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
