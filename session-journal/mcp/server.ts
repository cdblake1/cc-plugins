// session-journal MCP server: exposes `store` and `recall` tools over stdio,
// backed by the same SQLite store the journal hooks write to.
//
// Run via: node --experimental-strip-types ${CLAUDE_PLUGIN_ROOT}/mcp/server.ts
// with NODE_PATH=${CLAUDE_PLUGIN_DATA}/node_modules so the SDK resolves.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { openDb, now } from "../scripts/db.ts";

const server = new McpServer({ name: "session-journal", version: "0.1.0" });

server.registerTool(
  "store",
  {
    title: "Store a note",
    description:
      "Persist a note to cross-session memory. Use for facts, decisions, or context " +
      "that should survive across Claude Code sessions.",
    inputSchema: {
      body: z.string().min(1).describe("The note content to remember."),
      key: z.string().optional().describe("Optional label to group and look up related notes."),
    },
  },
  async ({ body, key }) => {
    const db = openDb();
    try {
      db.prepare("INSERT INTO notes (session_id, key, body, ts) VALUES (?, ?, ?, ?)").run(
        null,
        key ?? null,
        body,
        now(),
      );
    } finally {
      db.close();
    }
    return {
      content: [{ type: "text", text: `Stored note${key ? ` under key "${key}"` : ""}.` }],
    };
  },
);

server.registerTool(
  "recall",
  {
    title: "Recall notes",
    description:
      "Retrieve previously stored notes from cross-session memory. Filter by key and/or a " +
      "text query; returns most recent first.",
    inputSchema: {
      key: z.string().optional().describe("Only return notes stored under this key."),
      query: z.string().optional().describe("Case-insensitive substring to match in note bodies."),
      limit: z
        .number()
        .int()
        .positive()
        .max(100)
        .optional()
        .describe("Max notes to return (default 20)."),
    },
  },
  async ({ key, query, limit }) => {
    const db = openDb();
    try {
      const clauses: string[] = [];
      const params: (string | number)[] = [];
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
        .prepare(`SELECT id, key, body, ts FROM notes ${where} ORDER BY id DESC LIMIT ?`)
        .all(...params, limit ?? 20) as Array<{
        id: number;
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

const transport = new StdioServerTransport();
await server.connect(transport);
