"""Summarization strategies (free by default; Claude API opt-in and gated)."""

from __future__ import annotations

from .base import Summarizer, SummaryResult


def get_summarizer(mode: str, **kwargs) -> Summarizer:
    """Resolve a summarizer by mode. Heavy/optional deps are imported lazily."""
    mode = (mode or "extractive").strip().lower()
    if mode == "extractive":
        from .extractive import ExtractiveSummarizer
        return ExtractiveSummarizer(**kwargs)
    if mode == "emit":
        from .emit import EmitSummarizer
        return EmitSummarizer(**kwargs)
    if mode == "claude":
        from .claude import ClaudeSummarizer
        return ClaudeSummarizer(**kwargs)
    raise ValueError(f"unknown summarize mode: {mode!r} (known: extractive, emit, claude)")


__all__ = ["Summarizer", "SummaryResult", "get_summarizer"]
