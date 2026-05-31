"""Shared fixtures. Ensures the package is importable without an install and provides
an in-memory store plus fake source/summarizer doubles so no test touches the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make src/ importable when running `pytest` without `pip install -e .`.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ai_radar.models import FetchParams, SourceItem  # noqa: E402
from ai_radar.sources.base import ContentUnavailable, Source  # noqa: E402
from ai_radar.storage import Store  # noqa: E402


@pytest.fixture
def store() -> Store:
    s = Store.open(":memory:")
    yield s
    s.close()


class FakeSource(Source):
    name = "fake"

    def __init__(self, items=None, content="hello world content", unavailable=False):
        self._items = items or [
            SourceItem(source="fake", external_id="a1", url="http://x/a1", title="A1"),
            SourceItem(source="fake", external_id="a2", url="http://x/a2", title="A2"),
        ]
        self._content = content
        self._unavailable = unavailable

    def discover(self, params: FetchParams):
        return list(self._items)

    def fetch_content(self, item: SourceItem):
        if self._unavailable:
            raise ContentUnavailable("no content")
        return f"{item.title}: {self._content}", "en"


@pytest.fixture
def fake_source_factory():
    def make(**kwargs):
        return FakeSource(**kwargs)
    return make
