"""Structured, content-rich summaries via Sonnet (map-reduce).

map:    summarize_document  -> {main_idea, key_findings[], why_it_matters} per source
reduce: synthesize_topic    -> a "state of the field" writeup from the per-doc briefs
reduce²: synthesize_overview -> a cross-topic executive summary from the topic syntheses

Cost is tracked from real `usage` so callers can stop at a per-run budget. This is the only
new module that imports `anthropic`, and it does so lazily.
"""

from __future__ import annotations

import json
import re

from ..config import PRICING, anthropic_api_key

# ~3.5 chars/token; cap doc content fed to the model to bound cost on full-text papers.
_CHARS_PER_TOKEN = 3.5

_TYPE_HINT = {
    "paper": "a research paper",
    "article": "a blog post or news article",
    "discussion": "a forum / Hacker News discussion",
    "repo": "an open-source code repository",
    "video": "a video (described by its title and description only)",
    "transcript": "a video transcript",
}

_DOC_SYSTEM = (
    "You are an AI research analyst. Given ONE source about AI / ML / software engineering, "
    "produce a compact, content-rich brief so the reader never has to open the source. "
    "Respond with ONLY a JSON object and nothing else:\n"
    '{"main_idea": "1-2 sentence plain-English summary of what this is and claims",\n'
    ' "key_findings": ["3-6 concrete, specific bullets: numbers, results, methods, claims — not fluff"],\n'
    ' "why_it_matters": "1 sentence on why an AI engineer should care"}'
)

_TOPIC_SYSTEM = (
    "You are an AI research analyst writing a tight 'state of the field' briefing for a topic, "
    "using the provided per-source briefs. Write 3-6 sentences of flowing prose (markdown) that "
    "synthesize the main threads and notable developments. Be specific and non-repetitive; do not "
    "list every item. No preamble, no headings."
)

_OVERVIEW_SYSTEM = (
    "You are an AI research analyst writing the executive summary atop a multi-topic AI digest. "
    "From the per-topic syntheses, write 4-8 markdown bullet points capturing the most important "
    "cross-cutting developments this period. Each bullet: one crisp, specific takeaway. No preamble."
)


class DocumentSummarizer:
    def __init__(self, model: str, *, api_key: str | None = None, max_doc_tokens: int = 16000):
        self.model = model
        self._key = api_key or anthropic_api_key()
        self.max_doc_chars = int(max_doc_tokens * _CHARS_PER_TOKEN)
        self.cost_usd = 0.0
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _client_or_raise(self):
        if self._client is None:
            if not self._key:
                raise RuntimeError("structured summaries require ANTHROPIC_API_KEY")
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("install the 'anthropic' extra: pip install 'ai-radar[llm]'") from exc
            self._client = anthropic.Anthropic(api_key=self._key)
        return self._client

    def _rates(self) -> dict:
        return PRICING.get(self.model, {"input": 3.0, "output": 15.0})

    def _track(self, usage) -> None:
        r = self._rates()
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        self.cost_usd += in_tok / 1_000_000 * r["input"] + out_tok / 1_000_000 * r["output"]

    def _call(self, system: str, user: str, *, max_tokens: int) -> str:
        client = self._client_or_raise()
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        self._track(getattr(resp, "usage", None))
        return "".join(getattr(b, "text", "") for b in resp.content).strip()

    # --- map ---------------------------------------------------------------

    def summarize_document(self, content: str, content_type: str) -> dict:
        hint = _TYPE_HINT.get(content_type, "a source")
        body = (content or "")[: self.max_doc_chars]
        user = f"This source is {hint}.\n\nSOURCE:\n{body}"
        raw = self._call(_DOC_SYSTEM, user, max_tokens=700)
        return _parse_brief(raw)

    # --- reduce ------------------------------------------------------------

    def synthesize_topic(self, topic: str, briefs: list[dict]) -> str:
        if not briefs:
            return ""
        lines = []
        for b in briefs:
            mi = b.get("main_idea", "")
            kf = "; ".join(b.get("key_findings", []) or [])
            lines.append(f"- {mi} {('('+kf+')') if kf else ''}".strip())
        user = f"TOPIC: {topic}\n\nPER-SOURCE BRIEFS:\n" + "\n".join(lines[:60])
        return self._call(_TOPIC_SYSTEM, user, max_tokens=900)

    def synthesize_overview(self, topic_syntheses: dict[str, str]) -> str:
        if not topic_syntheses:
            return ""
        blocks = [f"## {t}\n{s}" for t, s in topic_syntheses.items() if s]
        if not blocks:
            return ""
        user = "PER-TOPIC SYNTHESES:\n\n" + "\n\n".join(blocks)
        return self._call(_OVERVIEW_SYSTEM, user, max_tokens=900)


def _parse_brief(raw: str) -> dict:
    """Tolerantly parse the model's JSON brief; degrade gracefully on malformed output."""
    obj = None
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return {"main_idea": (raw or "").strip()[:400], "key_findings": [], "why_it_matters": ""}
    findings = obj.get("key_findings") or []
    if isinstance(findings, str):
        findings = [findings]
    return {
        "main_idea": str(obj.get("main_idea", "")).strip(),
        "key_findings": [str(x).strip() for x in findings if str(x).strip()],
        "why_it_matters": str(obj.get("why_it_matters", "")).strip(),
    }
