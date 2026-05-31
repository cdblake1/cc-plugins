"""Claude summarizer — opt-in, key-gated, cost-estimated.

This is the ONLY module that imports `anthropic`, and it does so lazily inside
summarize() so the base install needs neither the dependency nor a key. estimate() is
pure arithmetic over the local token heuristic and never touches the network — it exists
so the user always sees a dollar figure before any paid request.
"""

from __future__ import annotations

from ..config import DEFAULT_MODEL, PRICING, anthropic_api_key
from .base import Summarizer, SummaryResult, estimate_tokens

_SYSTEM = (
    "You are an AI research analyst. Summarize the key learnings across the provided "
    "documents about a topic in AI/software engineering. Organize by theme; highlight "
    "concrete breakthroughs, model/tool updates, and actionable takeaways for an AI "
    "engineer. Be specific and cite document titles. Keep it tight."
)


class ClaudeSummarizer(Summarizer):
    mode = "claude"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
        api_key: str | None = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self._api_key = api_key  # if None, resolved from env at call time

    # --- pricing -----------------------------------------------------------

    def _rates(self) -> dict:
        if self.model not in PRICING:
            raise ValueError(
                f"no pricing for model {self.model!r}; known: {', '.join(PRICING)}"
            )
        return PRICING[self.model]

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        r = self._rates()
        return input_tokens / 1_000_000 * r["input"] + output_tokens / 1_000_000 * r["output"]

    def estimate(self, docs: list[str]) -> SummaryResult:
        prompt = self._build_prompt(docs)
        input_tokens = estimate_tokens(_SYSTEM) + estimate_tokens(prompt)
        output_tokens = self.max_tokens  # worst-case for budgeting
        cost = self._cost(input_tokens, output_tokens)
        return SummaryResult(
            mode=self.mode,
            summary="",
            model=self.model,
            token_usage={"input": input_tokens, "output": output_tokens},
            estimated_cost_usd=round(cost, 4),
            meta={
                "doc_count": len(docs),
                "note": "ESTIMATE ONLY — no API call made",
                "rates_per_mtok": self._rates(),
            },
        )

    def summarize(self, docs: list[str]) -> SummaryResult:
        key = self._api_key or anthropic_api_key()
        if not key:
            raise RuntimeError(
                "claude mode requires ANTHROPIC_API_KEY (set it in the environment or .env)"
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised via install extra
            raise RuntimeError(
                "claude mode needs the 'anthropic' package: pip install 'ai-radar[llm]'"
            ) from exc

        prompt = self._build_prompt(docs)
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(getattr(block, "text", "") for block in resp.content)
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        return SummaryResult(
            mode=self.mode,
            summary=text.strip(),
            model=self.model,
            token_usage={"input": in_tok, "output": out_tok},
            estimated_cost_usd=round(self._cost(in_tok, out_tok), 4),
            meta={"doc_count": len(docs), "actual": True},
        )

    def _build_prompt(self, docs: list[str]) -> str:
        parts = []
        for i, doc in enumerate(docs, 1):
            parts.append(f"## Document {i}\n{doc.strip()}")
        return "\n\n".join(parts)
