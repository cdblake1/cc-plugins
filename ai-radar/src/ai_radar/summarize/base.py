"""Summarizer seam + shared token/cost helpers.

estimate() must NEVER make an external call — it exists precisely so the user can see a
cost before any paid API request. summarize() does the real work.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SummaryResult:
    mode: str
    summary: str
    model: str | None = None
    token_usage: dict | None = None           # {"input": int, "output": int}
    estimated_cost_usd: float | None = None
    meta: dict = field(default_factory=dict)


class Summarizer(ABC):
    mode: str = ""

    @abstractmethod
    def estimate(self, docs: list[str]) -> SummaryResult:
        """Return a cost/coverage preview. No external/network call allowed."""
        raise NotImplementedError

    @abstractmethod
    def summarize(self, docs: list[str]) -> SummaryResult:
        """Produce the actual summary."""
        raise NotImplementedError


def estimate_tokens(text: str) -> int:
    """Cheap offline token estimate (~3.5 chars/token, +10% headroom).

    Deliberately heuristic so estimate() stays free and deterministic; actual usage is
    recorded from the API response when the Claude path runs.
    """
    if not text:
        return 0
    return int(len(text) / 3.5 * 1.1) + 1
