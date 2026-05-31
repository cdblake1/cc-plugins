"""Extractive summarizer — zero cost, no API key, deterministic.

A small frequency-based key-sentence picker across all documents. Not as fluent as an
LLM, but free and good enough to skim the learnings. The default mode.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .base import Summarizer, SummaryResult, estimate_tokens

_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]+")

_STOP = set(
    """the a an and or but if then else for to of in on at by with from as is are was were be been
    being this that these those it its it's they them their we you your i he she his her our us not
    no yes do does did done has have had will would can could should may might must about into over
    under more most some any all each new use using used also than via per which who whom whose what
    when where why how""".split()
)


class ExtractiveSummarizer(Summarizer):
    mode = "extractive"

    def __init__(self, max_sentences: int = 12):
        self.max_sentences = max_sentences

    def estimate(self, docs: list[str]) -> SummaryResult:
        total = sum(estimate_tokens(d) for d in docs)
        return SummaryResult(
            mode=self.mode,
            summary="",
            estimated_cost_usd=0.0,
            token_usage={"input": total, "output": 0},
            meta={"doc_count": len(docs), "note": "free / local — no API call"},
        )

    def summarize(self, docs: list[str]) -> SummaryResult:
        corpus = "\n".join(docs)
        freqs = self._word_frequencies(corpus)
        scored: list[tuple[float, int, str]] = []
        idx = 0
        for doc in docs:
            for sent in _split_sentences(doc):
                score = self._score(sent, freqs)
                if score > 0:
                    scored.append((score, idx, sent))
                    idx += 1
        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[: self.max_sentences]
        # Restore original reading order for readability.
        top.sort(key=lambda t: t[1])
        bullets = "\n".join(f"- {s.strip()}" for _, _, s in top)
        summary = bullets or "(no extractable sentences)"
        return SummaryResult(
            mode=self.mode,
            summary=summary,
            estimated_cost_usd=0.0,
            token_usage={"input": estimate_tokens(corpus), "output": 0},
            meta={"doc_count": len(docs), "sentences": len(top)},
        )

    def _word_frequencies(self, text: str) -> Counter:
        words = [w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOP]
        counts = Counter(words)
        if counts:
            peak = max(counts.values())
            for w in counts:
                counts[w] = counts[w] / peak  # normalize to 0..1
        return counts

    def _score(self, sentence: str, freqs: Counter) -> float:
        words = [w.lower() for w in _WORD_RE.findall(sentence) if w.lower() not in _STOP]
        if not words or len(words) < 4:
            return 0.0
        raw = sum(freqs.get(w, 0.0) for w in words)
        # Length-normalize so we don't just pick the longest sentences.
        return raw / math.sqrt(len(words))


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text) if len(s.strip()) > 20]
