// Tiny shared helper for hook scripts: read the event JSON Claude Code sends on stdin.
// Journaling hooks must never block the session, so callers should swallow errors
// and exit 0 regardless.

export async function readHookInput<T = Record<string, unknown>>(): Promise<T> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  return raw ? (JSON.parse(raw) as T) : ({} as T);
}
