// PostToolUse hook (matcher Write|Edit|MultiEdit): log one edit row per successful
// file-mutating tool call. PostToolUse fires only on success, which is exactly the
// set of edits we want to journal.
import { openDb, now } from "./db.ts";
import { readHookInput } from "./hooklib.ts";

try {
  const input = await readHookInput<{
    session_id?: string;
    tool_name?: string;
    tool_input?: { file_path?: string };
  }>();
  const tool = input.tool_name;
  if (tool) {
    const db = openDb();
    try {
      db.prepare("INSERT INTO edits (session_id, tool, file_path, ts) VALUES (?, ?, ?, ?)").run(
        input.session_id ?? null,
        tool,
        input.tool_input?.file_path ?? null,
        now(),
      );
    } finally {
      db.close();
    }
  }
} catch (err) {
  console.error("session-journal post-tooluse hook:", (err as Error).message);
}
process.exit(0);
