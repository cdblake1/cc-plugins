"""Auth/routing logic for the scale-to-zero HTTP front door (deploy/server.py).

Tests the pure token/authorization helpers without binding a socket or spawning runs.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

_SERVER_PY = Path(__file__).resolve().parent.parent / "deploy" / "server.py"


@pytest.fixture
def srv():
    spec = importlib.util.spec_from_file_location("ai_radar_http_server", _SERVER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _handler(path="/pull", auth=None):
    headers = {"Authorization": auth} if auth else {}
    return types.SimpleNamespace(path=path, headers=headers)


def test_token_from_bearer_header(srv, monkeypatch):
    monkeypatch.setenv("PULL_TOKEN", "secret")
    assert srv._authorized(_handler(auth="Bearer secret")) is True
    assert srv._authorized(_handler(auth="Bearer wrong")) is False


def test_token_from_query_string(srv, monkeypatch):
    monkeypatch.setenv("PULL_TOKEN", "secret")
    assert srv._authorized(_handler(path="/pull?token=secret")) is True
    assert srv._authorized(_handler(path="/pull?token=nope")) is False


def test_no_configured_token_refuses(srv, monkeypatch):
    """An unset PULL_TOKEN must NOT become an open trigger."""
    monkeypatch.delenv("PULL_TOKEN", raising=False)
    assert srv._authorized(_handler(auth="Bearer anything")) is False
    assert srv._authorized(_handler(path="/pull")) is False
