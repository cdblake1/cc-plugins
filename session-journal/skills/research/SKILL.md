---
name: research
description: >-
  Cost-aware research trigger. Use when the user wants something researched — a web/external topic
  or a question about this (or another) codebase — and you want the right amount of machinery for
  the question rather than always reaching for the heavy harness. Judges a route (web vs codebase)
  and a complexity tier (light/medium/heavy), confirms the rough cost before spending, runs the
  research keeping raw sources out of the main context, then saves a cited report for later recall.
---

You are running **cost-aware research**. The goal is a well-sourced answer that keeps the main
session context clean, using the *cheapest tier that can answer the question well*. Two principles
override everything else:

- **Context isolation:** raw sources (web pages, file dumps) must not land in the main context.
  Delegate the searching/reading to a subagent and keep only its conclusion — except for the
  lightest one-shot lookups.
- **No silent spend:** never run the medium or heavy tier without first confirming the proposed
  tier + rough cost with the user.

## Step 1 — Judge route and tier (your judgment, guided by these signals)

**Route — codebase vs web:**
- **Codebase** if the question references files, functions, symbols, configs, "this repo", "our
  code", "where is…", "how does X work here", or otherwise points at a code/project artifact.
- **Web** if it's about external/topical/current information, libraries' upstream behavior, prices,
  news, comparisons, or anything not answerable from local code.
- **Ambiguous?** Don't guess — ask a one-line clarifying question, or offer the route choice in the
  Step 2 confirm prompt.

**Tier — how much machinery the answer needs:**
- **Light** (≈ a few k tokens): a single fact or a narrow lookup answerable from 1–2 sources. One
  or two searches, or a single quick subagent. May run inline if it's genuinely one-shot.
- **Medium** (≈ 10–30k tokens): needs synthesis across several sources or a sweep of the codebase,
  but not formal fact-checking. Delegate to one `Explore` (codebase) or `general-purpose` (web)
  subagent that searches in its own context and returns only the conclusion.
- **Heavy** (≈ 100k+ tokens): broad, multi-source, or claims that must be cross-checked/verified.
  Use the `deep-research` skill (web) or a `Workflow` fan-out → verify → synthesize.

Pick the tier from how many distinct sources are needed, the breadth/ambiguity of the question, and
whether claims need cross-checking — not from question length alone.

## Step 2 — Confirm before spending

Use **`AskUserQuestion`** to present what you propose to do before running medium/heavy work:
- State the **route**, the **tier**, and a **qualitative cost estimate with a token range**
  (e.g. "Medium tier, web · ≈ 10–30k tokens").
- Offer options: **Proceed**, **Change tier** (let them pick light/medium/heavy), **Cancel**.
- If the route was ambiguous, fold the route choice into this prompt too.

A pure **Light** one-shot lookup may skip the prompt (it's cheap and the user asked) — but if
there's any doubt about cost, confirm.

## Step 3 — Run the research

Per the confirmed tier:

- **Light:** run 1–2 `WebSearch`/`WebFetch` calls (web) or a quick targeted search (codebase). Pull
  full pages only when a snippet won't do. Keep it minimal.
- **Medium:** spawn **one** subagent (`Explore` for codebase, `general-purpose` for web) with a
  precise brief: what to find, what to return. Instruct it to return **only the synthesized
  conclusion + the sources it used**, not raw page/file contents. You keep the conclusion.
- **Heavy:** invoke the `deep-research` skill (web) with the refined question, or author a
  `Workflow` (fan-out searchers → adversarial verify → synthesize) for codebase-scale or
  mixed work.

**Model-tier routing (cost lever):** for medium/heavy, let bulk fetching/searching run on cheaper
models and reserve the strongest model for synthesis/verification. Don't pay top-tier rates to read
pages. (Subagents inherit a sensible default; only override the model when a step clearly warrants
a cheaper or stronger one.)

If the research turns up nothing useful, say so honestly in the report rather than padding it.

## Step 4 — Persist the report

<!-- PERSIST BLOCK — swap for a dedicated research store if one lands. -->
Save the final report via `mcp__session-journal__store`:
- `key: "research"`
- `tags: ["research", <route>, <tier>]`  (e.g. `["research", "web", "medium"]`)
- `body`: the report, prefixed with a short metadata header — the **original question**, the
  **tier + route** used, and the **sources consulted** (URLs or file paths).

This store call is best-effort: if it fails, **still return the report inline** — don't lose the
work. Saving metadata is cheap (a small one-shot call) and makes the report findable via `recall`.
<!-- END PERSIST BLOCK -->

## Step 5 — Present

Return the report inline to the user, lead with the direct answer, then supporting detail and the
cited sources. Note that it's been saved (and recallable) when the store succeeded.
