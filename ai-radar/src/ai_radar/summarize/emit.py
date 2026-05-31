"""Emit summarizer — zero cost, no API key.

Doesn't summarize itself; it assembles the documents into one clean, structured digest
that an external agent (e.g. Claude Code reading the CLI output) can summarize for free.
Useful when you're already in an agent session and don't want to spend on the API.
"""

from __future__ import annotations

from .base import Summarizer, SummaryResult, estimate_tokens

_INSTRUCTION = (
    "# Source documents for summarization\n\n"
    "Below are the fetched documents. Summarize the key learnings across them: group by "
    "theme, call out concrete breakthroughs/updates, and note anything actionable for an "
    "AI engineer. Cite document titles where relevant.\n"
)


class EmitSummarizer(Summarizer):
    mode = "emit"

    def estimate(self, docs: list[str]) -> SummaryResult:
        total = sum(estimate_tokens(d) for d in docs)
        return SummaryResult(
            mode=self.mode,
            summary="",
            estimated_cost_usd=0.0,
            token_usage={"input": total, "output": 0},
            meta={"doc_count": len(docs), "note": "free — emits a digest for an agent to summarize"},
        )

    def summarize(self, docs: list[str]) -> SummaryResult:
        parts = [_INSTRUCTION]
        for i, doc in enumerate(docs, 1):
            parts.append(f"\n---\n\n## Document {i}\n\n{doc.strip()}\n")
        digest = "\n".join(parts)
        return SummaryResult(
            mode=self.mode,
            summary=digest,
            estimated_cost_usd=0.0,
            token_usage={"input": estimate_tokens(digest), "output": 0},
            meta={"doc_count": len(docs)},
        )
