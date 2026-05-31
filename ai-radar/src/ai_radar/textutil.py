"""Small text helpers shared by FTS search, cross-referencing, and wiki generation.

Deliberately dependency-free so storage.py (stdlib-only) can use it.
"""

from __future__ import annotations

import html
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'+-]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    """Unescape HTML entities (e.g. &#x2F; → /), strip tags, collapse whitespace.

    Shared by the RSS/HN/arXiv/etc. sources so stored content is clean for both reading
    and summarization.
    """
    if not raw:
        return ""
    unescaped = html.unescape(raw)
    stripped = _TAG_RE.sub(" ", unescaped)
    # A second unescape catches entities that were hidden inside tags.
    return _WS_RE.sub(" ", html.unescape(stripped)).strip()

STOPWORDS = set(
    """the a an and or but if then else for to of in on at by with from as is are was were be been
    being this that these those it its they them their we you your our us not no yes do does did done
    has have had will would can could should may might must about into over under more most some any
    all each new use using used also than via per which who whom whose what when where why how out up
    down off again further once here there why all both few other such only own same so too very just
    one two three first second new like get got make made see use using""".split()
)


def tokens(text: str) -> list[str]:
    """Lowercase content words, stopwords and very short tokens removed."""
    return [w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in STOPWORDS]


def top_terms(text: str, n: int = 12) -> list[str]:
    """The n most frequent content terms in a piece of text."""
    counts = Counter(tokens(text))
    return [term for term, _ in counts.most_common(n)]


def fts_match_query(text: str, max_terms: int = 20) -> str:
    """Build a safe FTS5 MATCH expression: top terms quoted and OR'd together.

    Quoting each term as a phrase neutralizes FTS5 operator characters in user input.
    Returns "" when there is nothing searchable (caller should skip the query).
    """
    terms = []
    seen = set()
    for t in tokens(text):
        if t in seen:
            continue
        seen.add(t)
        terms.append(t)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in terms)
