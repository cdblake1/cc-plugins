// Pure guardrail policy: classify a Bash command as allow / ask / deny.
// No I/O and no side effects, so it is imported directly by both the hook and the
// unit tests (scripts/guardrail.test.ts).

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

/** Escape a branch name for safe inclusion in a RegExp. */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function evaluate(
  commandRaw: string,
  protectedBranches: string[] = ["main", "master"],
): Decision {
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
  const branches = protectedBranches.filter(Boolean).map(escapeRegExp);
  const hitsProtected =
    branches.length > 0 && new RegExp(`\\b(${branches.join("|")})\\b`, "i").test(c);

  // DENY: force-push to a protected branch.
  if (isGitPush && hasForce && hitsProtected) {
    return {
      decision: "deny",
      reason: `Force-pushing to a protected branch (${protectedBranches.join("/")}) is blocked.`,
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
