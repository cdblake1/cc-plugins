// Git context helper (v3). Used by hooks and (bundled into) the MCP server to scope memory
// by repository. All git calls are best-effort: they never throw and return null off-repo.

import { execSync } from "node:child_process";
import { basename } from "node:path";

export type GitContext = { repo: string | null; branch: string | null; commit: string | null };

function run(cmd: string, cwd: string): string | null {
  try {
    const out = execSync(cmd, {
      cwd,
      encoding: "utf8",
      timeout: 5000,
      stdio: ["ignore", "pipe", "ignore"],
    });
    return out.trim() || null;
  } catch {
    return null;
  }
}

/**
 * PURE: normalize a git remote URL (or path) into a stable repo id like "owner/name".
 * Handles https, ssh (git@host:owner/name.git), embedded credentials, and trailing .git.
 */
export function normalizeRepo(urlOrPath: string): string {
  let s = (urlOrPath ?? "").trim();
  if (!s) return s;
  s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//i, ""); // strip scheme (https://, ssh://, git://)
  s = s.replace(/^[^@/]+@/, ""); // strip user@ / user:token@
  s = s.replace(":", "/"); // scp-style host:owner/name -> host/owner/name
  s = s.replace(/\.git$/i, "");
  const parts = s.split("/").filter(Boolean);
  // host/owner/name -> owner/name; shorter inputs returned as-is
  return parts.length >= 3 ? parts.slice(-2).join("/") : parts.join("/");
}

/** PURE: extract the branch name from a symbolic-ref like "refs/remotes/origin/main". */
export function parseDefaultBranchRef(ref: string): string | null {
  const m = (ref ?? "").trim().match(/[^/\s]+$/);
  return m ? m[0] : null;
}

/** Resolve {repo, branch, commit} for `cwd`. Nulls when not in a git repo. */
export function gitContext(cwd: string): GitContext {
  const root = run("git rev-parse --show-toplevel", cwd);
  if (!root) return { repo: null, branch: null, commit: null };
  const remote = run("git config --get remote.origin.url", cwd);
  const repo = remote ? normalizeRepo(remote) : basename(root);
  return {
    repo: repo || null,
    branch: run("git rev-parse --abbrev-ref HEAD", cwd),
    commit: run("git rev-parse --short HEAD", cwd),
  };
}

/** The repo's default branch (e.g. "main"/"develop"), or null if undeterminable. */
export function defaultBranch(cwd: string): string | null {
  const ref = run("git symbolic-ref --quiet refs/remotes/origin/HEAD", cwd);
  if (ref) return parseDefaultBranchRef(ref);
  return run("git config --get init.defaultBranch", cwd);
}
