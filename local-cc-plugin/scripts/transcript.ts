// Transcript / context-budget helpers (v7 context-efficiency). Mirrors rollup.ts: the top half is
// pure (parse a usage line, sum live tokens, format a budget, parse the userConfig) and is unit-
// tested without IO; the bottom half is bounded filesystem IO (read the latest usage from a
// transcript JSONL, locate the active transcript for a project) used by the UserPromptSubmit nudge
// hook and the `context_budget` MCP tool.
//
// Context occupancy is read from the transcript JSONL Claude Code writes: each assistant entry
// carries `message.usage` with input/cache token counts. Live context window occupancy ≈ the sum
// of the three input-side numbers (input + cache_read + cache_creation) on the LATEST assistant
// entry — confirmed empirically against a real transcript. Output tokens are NOT part of the
// resident context, so they're excluded.

import { closeSync, fstatSync, openSync, readdirSync, readSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/** Default context window (tokens) when none is configured. Model-dependent — overridable. */
export const DEFAULT_CONTEXT_WINDOW = 200_000;

/** How far back from EOF we read before falling back to a full scan. The latest assistant entry
 * sits near EOF, so this comfortably covers the common case without loading the whole file. */
const TAIL_BYTES = 256 * 1024;

export type ContextUsage = {
  input: number;
  cacheRead: number;
  cacheCreate: number;
  output: number;
};

export type BudgetTier = "ok" | "warn" | "high";
export type Budget = {
  tokens: number;
  windowTokens: number;
  pct: number;
  tier: BudgetTier;
  label: string;
};

export type BudgetConfig = { warnPct: number; window: number };

// ---------------------------------------------------------------------------------------------
// PURE
// ---------------------------------------------------------------------------------------------

function finite(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

/**
 * PURE: parse one transcript JSONL line into a ContextUsage, or null if it isn't an assistant
 * message carrying usage. Never throws (malformed JSON → null). Missing individual token fields
 * coerce to 0; a line with none of the four token fields is treated as "not a usage line".
 */
export function parseUsageLine(line: string): ContextUsage | null {
  if (!line) return null;
  let obj: unknown;
  try {
    obj = JSON.parse(line);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  const o = obj as { type?: unknown; message?: { usage?: Record<string, unknown> } };
  if (o.type !== "assistant") return null;
  const u = o.message?.usage;
  if (!u || typeof u !== "object") return null;
  const present =
    u.input_tokens != null ||
    u.cache_read_input_tokens != null ||
    u.cache_creation_input_tokens != null ||
    u.output_tokens != null;
  if (!present) return null;
  return {
    input: finite(u.input_tokens),
    cacheRead: finite(u.cache_read_input_tokens),
    cacheCreate: finite(u.cache_creation_input_tokens),
    output: finite(u.output_tokens),
  };
}

/** PURE: resident context occupancy = input + cache_read + cache_creation (output excluded). */
export function liveContextTokens(u: ContextUsage): number {
  return u.input + u.cacheRead + u.cacheCreate;
}

/** PURE: compact "12k"/"950" token formatting. */
function fmtK(n: number): string {
  return n < 1000 ? String(Math.max(0, Math.round(n))) : `${Math.round(n / 1000)}k`;
}

/**
 * PURE: turn a live-token count into a budget report. `tier` uses fixed bands (warn ≥ 70%,
 * high ≥ 90%) for display; the nudge hook decides whether to *emit* using its own configured
 * threshold, independent of these bands.
 */
export function formatBudget(tokens: number, windowTokens: number = DEFAULT_CONTEXT_WINDOW): Budget {
  const win = windowTokens > 0 ? windowTokens : DEFAULT_CONTEXT_WINDOW;
  const pct = Math.round((tokens / win) * 100);
  const tier: BudgetTier = pct >= 90 ? "high" : pct >= 70 ? "warn" : "ok";
  return { tokens, windowTokens: win, pct, tier, label: `~${fmtK(tokens)} / ${fmtK(win)} tokens (${pct}%)` };
}

/**
 * PURE: parse the opt-in budget config from the environment (exported by Claude Code as
 * CLAUDE_PLUGIN_OPTION_*). Returns null when disabled (warn pct unset/blank/invalid), matching the
 * Stop hygiene gate's "nothing configured → no-op" default. Window falls back to the default.
 */
export function parseBudgetConfig(env: Record<string, string | undefined>): BudgetConfig | null {
  const raw = env.CLAUDE_PLUGIN_OPTION_CONTEXT_BUDGET_WARN_PCT;
  if (raw == null || raw.trim() === "") return null;
  const warnPct = Number(raw);
  if (!Number.isFinite(warnPct) || warnPct <= 0 || warnPct > 100) return null;
  const winRaw = env.CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS;
  const winNum = winRaw == null ? NaN : Number(winRaw);
  const window = Number.isFinite(winNum) && winNum > 0 ? winNum : DEFAULT_CONTEXT_WINDOW;
  return { warnPct, window };
}

// ---------------------------------------------------------------------------------------------
// IO (bounded, best-effort — never throws; returns null on any failure)
// ---------------------------------------------------------------------------------------------

/** Scan a byte range [start, EOF) of a file for the LAST parseable usage line. */
function scanFromOffset(path: string, start: number): ContextUsage | null {
  let fd: number | undefined;
  try {
    fd = openSync(path, "r");
    const size = fstatSync(fd).size;
    const from = Math.max(0, start);
    const len = size - from;
    if (len <= 0) return null;
    const buf = Buffer.allocUnsafe(len);
    readSync(fd, buf, 0, len, from);
    const lines = buf.toString("utf8").split("\n");
    // If we began mid-file, the first fragment is a partial line — drop it.
    if (from > 0 && lines.length > 1) lines.shift();
    for (let i = lines.length - 1; i >= 0; i--) {
      const u = parseUsageLine(lines[i].trim());
      if (u) return u;
    }
    return null;
  } catch {
    return null;
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        /* ignore */
      }
    }
  }
}

/**
 * IO: read the most recent ContextUsage from a transcript JSONL. Reads a bounded tail first
 * (TAIL_BYTES); only if that window contained no usage line AND the file is larger does it fall
 * back to a single full scan. Returns null if the file is missing/unreadable or has no usage line.
 */
export function readLatestUsage(transcriptPath: string, tailBytes: number = TAIL_BYTES): ContextUsage | null {
  let size = 0;
  try {
    size = statSync(transcriptPath).size;
  } catch {
    return null;
  }
  const tailStart = Math.max(0, size - tailBytes);
  const fromTail = scanFromOffset(transcriptPath, tailStart);
  if (fromTail) return fromTail;
  // Tail missed (e.g. the last entry is larger than the window) — scan the whole file once.
  return tailStart > 0 ? scanFromOffset(transcriptPath, 0) : null;
}

/**
 * PURE-ish: the directory Claude Code writes this project's transcripts to. Observed convention
 * (not a documented contract): `<configDir>/projects/<projectDir with each non-alphanumeric char
 * replaced by '-'>`. configDir defaults to $CLAUDE_CONFIG_DIR or ~/.claude.
 */
export function transcriptDirFor(projectDir: string, configDir?: string): string {
  const base = configDir ?? process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), ".claude");
  const slug = projectDir.replace(/[^A-Za-z0-9]/g, "-");
  return join(base, "projects", slug);
}

/** IO: newest `*.jsonl` transcript (by mtime) for a project, or null if none/unreadable. */
export function latestTranscriptPath(projectDir: string, configDir?: string): string | null {
  try {
    const dir = transcriptDirFor(projectDir, configDir);
    let best: { path: string; mtime: number } | null = null;
    for (const f of readdirSync(dir)) {
      if (!f.endsWith(".jsonl")) continue;
      const p = join(dir, f);
      const mtime = statSync(p).mtimeMs;
      if (!best || mtime > best.mtime) best = { path: p, mtime };
    }
    return best?.path ?? null;
  } catch {
    return null;
  }
}
