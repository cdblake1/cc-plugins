// Unit tests for the pure parts of gitctx (URL/ref normalization). The git-running parts
// are I/O and covered by integration. Run via `npm test`.
import { normalizeRepo, parseDefaultBranchRef } from "./gitctx.ts";

let failed = 0;
function eq(name: string, got: string | null, want: string | null): void {
  if (got !== want) {
    failed++;
    console.error(`FAIL ${name}: got '${got}' want '${want}'`);
  }
}

eq("https", normalizeRepo("https://github.com/owner/name.git"), "owner/name");
eq("scp-ssh", normalizeRepo("git@github.com:owner/name.git"), "owner/name");
eq("https-creds", normalizeRepo("https://user:token@github.com/owner/name.git"), "owner/name");
eq("ssh-url", normalizeRepo("ssh://git@github.com/owner/name.git"), "owner/name");
eq("no-dotgit", normalizeRepo("https://github.com/owner/name"), "owner/name");

eq("ref-main", parseDefaultBranchRef("refs/remotes/origin/main"), "main");
eq("ref-develop", parseDefaultBranchRef("refs/remotes/origin/develop"), "develop");

if (failed > 0) {
  console.error(`\ngitctx: ${failed} assertion(s) FAILED`);
  process.exit(1);
}
console.log("gitctx: all assertions pass");
