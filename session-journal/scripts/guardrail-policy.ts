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

/**
 * Crude whitespace tokenization — good enough for guardrail heuristics. Finds `cmd`, then
 * checks whether any following non-flag, non-mode argument is a catastrophic target
 * (/, ~, $HOME, ..). Skips octal modes so `chmod` can reuse it.
 */
function hasDangerousTargetAfter(command: string, cmd: string): boolean {
  const tokens = command.split(/\s+/);
  const idx = tokens.findIndex((t) => t === cmd || t.endsWith(`/${cmd}`));
  if (idx === -1) return false;
  for (let i = idx + 1; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.startsWith("-")) continue; // a flag
    if (/^[0-7]{3,4}$/.test(t)) continue; // an octal mode, e.g. chmod 777
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

  // DENY: fork bomb — a function that pipes itself, e.g. :(){ :|:& };:
  if (/(^|[\s;&|])([a-zA-Z_:][\w:]*)\s*\(\)\s*\{[^}]*\2\s*\|\s*\2[^}]*&[^}]*\}/.test(c)) {
    return { decision: "deny", reason: "Fork bomb pattern is blocked." };
  }

  // DENY: writing an image straight to a block device, or formatting one.
  if (/\bdd\b[^|;&\n]*\bof=\/dev\/(sd|nvme|vd|hd|disk|mmcblk|loop)\w*/i.test(c)) {
    return { decision: "deny", reason: "dd writing to a block device is blocked." };
  }
  if (/\bmkfs(\.\w+)?\b[^|;&\n]*\/dev\/\w+/i.test(c)) {
    return { decision: "deny", reason: "Formatting a block device (mkfs) is blocked." };
  }

  // DENY: recursive chmod 777 on a catastrophic target.
  const chmodRecursive = /\bchmod\b[^|&;]*?(?:\s-[a-z]*R[a-z]*|\s--recursive)\b/i.test(c);
  if (chmodRecursive && /\bchmod\b[^|&;]*\b777\b/i.test(c) && hasDangerousTargetAfter(c, "chmod")) {
    return { decision: "deny", reason: "Recursive chmod 777 on /, ~, or $HOME is blocked." };
  }

  // DENY: recursive + force rm targeting /, ~, $HOME, or ..
  const rmRecursive = /\brm\b[^|&;]*?(?:\s-[a-z]*r[a-z]*|\s--recursive)\b/i.test(c);
  const rmForce = /\brm\b[^|&;]*?(?:\s-[a-z]*f[a-z]*|\s--force)\b/i.test(c);
  if (rmRecursive && rmForce && hasDangerousTargetAfter(c, "rm")) {
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
