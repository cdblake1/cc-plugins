// session-journal MCP server: exposes `store` and `recall` tools over stdio,
// backed by the same SQLite store the journal hooks write to.
//
// Run via: node --experimental-strip-types ${CLAUDE_PLUGIN_ROOT}/mcp/server.ts
// with NODE_PATH=${CLAUDE_PLUGIN_DATA}/node_modules so the SDK resolves.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { openDb, now } from "../scripts/db.ts";
import { gitContext } from "../scripts/gitctx.ts";

const server = new McpServer({ name: "session-journal", version: "0.3.0" });

// Repo this server is scoped to, derived from the project dir (exported by Claude Code).
// Used to tag stored notes and to scope recall by default.
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
const CURRENT_REPO = gitContext(PROJECT_DIR).repo;

server.registerTool(
  "store",
  {
    title: "Store a note",
    description:
      "Persist a note to cross-session memory. Use for facts, decisions, or context " +
      "that should survive across Claude Code sessions. Notes are tagged with the current " +
      "repository so they surface automatically in future sessions on the same repo.",
    inputSchema: {
      body: z.string().min(1).describe("The note content to remember."),
      key: z.string().optional().describe("Optional label to group and look up related notes."),
    },
  },
  async ({ body, key }) => {
    const db = openDb();
    try {
      db.prepare("INSERT INTO notes (session_id, repo, key, body, ts) VALUES (?, ?, ?, ?, ?)").run(
        null,
        CURRENT_REPO,
        key ?? null,
        body,
        now(),
      );
    } finally {
      db.close();
    }
    const scopeNote = CURRENT_REPO ? ` for ${CURRENT_REPO}` : "";
    return {
      content: [{ type: "text", text: `Stored note${key ? ` under key "${key}"` : ""}${scopeNote}.` }],
    };
  },
);

server.registerTool(
  "recall",
  {
    title: "Recall notes",
    description:
      "Retrieve previously stored notes from cross-session memory. By default returns notes " +
      "for the current repository (plus un-scoped notes); pass scope:'all' to search every repo. " +
      "Filter by key and/or a text query; returns most recent first.",
    inputSchema: {
      key: z.string().optional().describe("Only return notes stored under this key."),
      query: z.string().optional().describe("Case-insensitive substring to match in note bodies."),
      scope: z
        .enum(["repo", "all"])
        .optional()
        .describe("'repo' (default) = current repo + un-scoped notes; 'all' = every repo."),
      limit: z
        .number()
        .int()
        .positive()
        .max(100)
        .optional()
        .describe("Max notes to return (default 20)."),
    },
  },
  async ({ key, query, scope, limit }) => {
    const db = openDb();
    try {
      const clauses: string[] = [];
      const params: (string | number)[] = [];
      // Repo scoping (default). Skipped when scope='all' or when we can't tell the repo.
      if (scope !== "all" && CURRENT_REPO) {
        clauses.push("(repo = ? OR repo IS NULL)");
        params.push(CURRENT_REPO);
      }
      if (key) {
        clauses.push("key = ?");
        params.push(key);
      }
      if (query) {
        clauses.push("body LIKE ?");
        params.push(`%${query}%`);
      }
      const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
      const rows = db
        .prepare(`SELECT id, repo, key, body, ts FROM notes ${where} ORDER BY id DESC LIMIT ?`)
        .all(...params, limit ?? 20) as Array<{
        id: number;
        repo: string | null;
        key: string | null;
        body: string;
        ts: string;
      }>;

      if (rows.length === 0) {
        return { content: [{ type: "text", text: "No matching notes." }] };
      }
      const text = rows
        .map((r) => `#${r.id} [${r.ts}]${r.key ? ` (${r.key})` : ""}: ${r.body}`)
        .join("\n");
      return { content: [{ type: "text", text }] };
    } finally {
      db.close();
    }
  },
);

server.registerTool(
  "journal",
  {
    title: "Recent activity",
    description:
      "List recent file edits recorded for the current repository (newest first) — useful to " +
      "recall what was changed in past sessions on this repo.",
    inputSchema: {
      limit: z
        .number()
        .int()
        .positive()
        .max(100)
        .optional()
        .describe("Max edits to return (default 20)."),
    },
  },
  async ({ limit }) => {
    if (!CURRENT_REPO) {
      return {
        content: [{ type: "text", text: "Not in a recognized git repository; no scoped activity." }],
      };
    }
    const db = openDb();
    try {
      const rows = db
        .prepare(
          "SELECT e.tool, e.file_path, e.ts FROM edits e JOIN sessions s ON e.session_id = s.id " +
            "WHERE s.repo = ? ORDER BY e.id DESC LIMIT ?",
        )
        .all(CURRENT_REPO, limit ?? 20) as Array<{
        tool: string;
        file_path: string | null;
        ts: string;
      }>;
      if (rows.length === 0) {
        return { content: [{ type: "text", text: `No recorded edits for ${CURRENT_REPO} yet.` }] };
      }
      const text = rows.map((r) => `${r.ts}  ${r.tool}  ${r.file_path ?? "(no path)"}`).join("\n");
      return { content: [{ type: "text", text: `Recent edits for ${CURRENT_REPO}:\n${text}` }] };
    } finally {
      db.close();
    }
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
