"""Make network access a test failure unless a test supplies its own fake."""

import pytest
import requests


@pytest.fixture(autouse=True)
def block_http(monkeypatch):
    """Block accidental requests from any unit or integration test."""
    def blocked(*args, **kwargs):
        raise AssertionError("Network requests are disabled in tests; use fake responses")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
