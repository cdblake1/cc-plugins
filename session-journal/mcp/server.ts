// session-journal MCP server: registration shell. All tool behavior lives in
// ./handlers.ts so it can be unit-tested directly. This file only knows about
// schema definitions, the DB lifecycle around each call, and the repo context.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { openDb } from "../scripts/db.ts";
import { gitContext } from "../scripts/gitctx.ts";
import {
  handleForget,
  handleJournal,
  handlePin,
  handleRecall,
  handleStore,
} from "./handlers.ts";

const server = new McpServer({ name: "session-journal", version: "0.6.0" });

// Repo this server is scoped to, derived from the project dir (exported by Claude Code).
// Used to tag stored notes and to scope recall by default.
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
const CURRENT_REPO = gitContext(PROJECT_DIR).repo;

function asText(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

server.registerTool(
  "store",
  {
    title: "Store a note",
    description:
      "Persist a note to cross-session memory. Use for facts, decisions, or context " +
      "that should survive across Claude Code sessions. Notes are tagged with the current " +
      "repository so they surface automatically in future sessions on the same repo. " +
      "Pass `tags` to make a note discoverable under multiple topics.",
    inputSchema: {
      body: z.string().min(1).describe("The note content to remember."),
      key: z.string().optional().describe("Optional label to group and look up related notes."),
      tags: z
        .array(z.string().min(1))
        .optional()
        .describe("Optional list of topic tags. Lowercased and de-duped on store."),
    },
  },
  async ({ body, key, tags }) => {
    const db = openDb();
    try {
      return asText(handleStore(db, { body, key, tags }, CURRENT_REPO));
    } finally {
      db.close();
    }
  },
);

server.registerTool(
  "recall",
  {
    title: "Recall notes",
    description:
      "Retrieve previously stored notes from cross-session memory. By default returns notes " +
      "for the current repository (plus un-scoped notes); pass scope:'all' to search every repo. " +
      "Filter by key, tags, an FTS5 text query, and/or a date range (since/until ISO timestamps). " +
      "Returns most recent first.",
    inputSchema: {
      key: z.string().optional().describe("Only return notes stored under this key."),
      tags: z
        .array(z.string().min(1))
        .optional()
        .describe("Match notes carrying any of these tags."),
      query: z
        .string()
        .optional()
        .describe("Full-text search over note bodies (FTS5; treated as a phrase)."),
      since: z
        .string()
        .optional()
        .describe("Only return notes stored at or after this ISO-8601 timestamp."),
      until: z
        .string()
        .optional()
        .describe("Only return notes stored at or before this ISO-8601 timestamp."),
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
  async ({ key, tags, query, since, until, scope, limit }) => {
    const db = openDb();
    try {
      return asText(
        handleRecall(db, { key, tags, query, since, until, scope, limit }, CURRENT_REPO),
      );
    } finally {
      db.close();
    }
  },
);

server.registerTool(
  "forget",
  {
    title: "Forget a note",
    description:
      "Delete a stored note. Pass `id` to remove one note. To bulk-delete every note under " +
      "a given key, pass `key` plus `confirm:\"yes\"`; without the confirmation the call refuses.",
    inputSchema: {
      id: z
        .number()
        .int()
        .positive()
        .optional()
        .describe("Note id to delete (from a prior `recall`)."),
      key: z.string().optional().describe("Delete all notes under this key (requires confirm)."),
      confirm: z
        .literal("yes")
        .optional()
        .describe("Required when bulk-deleting by key."),
    },
  },
  async ({ id, key, confirm }) => {
    const db = openDb();
    try {
      return asText(handleForget(db, { id, key, confirm }));
    } finally {
      db.close();
    }
  },
);

server.registerTool(
  "pin",
  {
    title: "Pin a note",
    description:
      "Mark a note so it is surfaced first on every SessionStart for this repo. Pass " +
      "`pinned:false` to unpin. Use sparingly — pinned notes appear above the checkpoint " +
      "and eat the recall context budget.",
    inputSchema: {
      id: z.number().int().positive().describe("Note id to pin or unpin."),
      pinned: z
        .boolean()
        .optional()
        .describe("Defaults to true. Set false to unpin."),
    },
  },
  async ({ id, pinned }) => {
    const db = openDb();
    try {
      return asText(handlePin(db, { id, pinned }));
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
    const db = openDb();
    try {
      return asText(handleJournal(db, { limit }, CURRENT_REPO));
    } finally {
      db.close();
    }
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
