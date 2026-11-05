"""Check private-state configuration without contacting GitHub."""

from unittest.mock import Mock

import pytest
import requests

from scripts.check_state_repository import verify_private_repository


@pytest.mark.parametrize("body", [{"private": False}, {}, [], {"private": "true"}])
def test_public_or_invalid_metadata_stops_delivery(monkeypatch, body):
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(status_code=200, json=lambda: body)))
    with pytest.raises(ValueError, match="must be private"):
        verify_private_repository("OWNER/state", "fake-token")


def test_private_repository_and_bounded_request(monkeypatch):
    get = Mock(return_value=Mock(status_code=200, json=lambda: {"private": True}))
    monkeypatch.setattr(requests, "get", get)
    verify_private_repository("OWNER/state", "fake-token")
    assert get.call_args.args == ("https://api.github.com/repos/OWNER/state",)
    assert get.call_args.kwargs["timeout"] == (10, 30)
    assert get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status", [301, 403, 404, 429, 500])
def test_failed_lookup_is_not_treated_as_private(monkeypatch, status):
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(status_code=status)))
    with pytest.raises(ValueError, match="Cannot verify"):
        verify_private_repository("OWNER/state", "fake-token")


def test_request_error_does_not_expose_token(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.ConnectionError("fake-token")))
    with pytest.raises(ValueError) as error:
        verify_private_repository("OWNER/state", "fake-token")
    assert "fake-token" not in str(error.value)


@pytest.mark.parametrize("repository,token", [("../state", "token"), ("OWNER/state", ""),
                                            ("https://example.com/repo", "token")])
def test_invalid_configuration_never_requests(monkeypatch, repository, token):
    get = Mock()
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValueError):
        verify_private_repository(repository, token)
    get.assert_not_called()
