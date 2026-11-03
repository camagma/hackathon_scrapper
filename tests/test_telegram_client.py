"""Exercise plain HTTP delivery with fake responses and no Telegram access."""

import json
from unittest.mock import Mock

import pytest
import requests

from devpost_reminder.telegram import TelegramClient, TelegramCredentials, TelegramError


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = (body if isinstance(body, str) else json.dumps(body)).encode()
    result._content_consumed = True
    return result


@pytest.fixture
def client():
    session = Mock()
    session.post.return_value = response({"ok": True, "result": {"message_id": 123}})
    return TelegramClient(TelegramCredentials("fake-test-token", "12345"), session), session


def test_plain_json_post_with_timeout_and_no_redirects(client):
    sender, session = client
    text = "Проект <AI> & агент\nhttps://example.com/"
    assert sender.send_message(text) is None
    session.post.assert_called_once_with(
        "https://api.telegram.org/botfake-test-token/sendMessage",
        json={"chat_id": "12345", "text": text}, timeout=(10, 30), allow_redirects=False,
    )


@pytest.mark.parametrize("text", ["", "   ", "a" * 4097, None])
def test_invalid_text_does_not_make_a_request(client, text):
    sender, session = client
    with pytest.raises(ValueError):
        sender.send_message(text)
    session.post.assert_not_called()


def test_maximum_text_is_accepted(client):
    client[0].send_message("a" * 4096)
    client[1].post.assert_called_once()


@pytest.mark.parametrize("body,status", [
    ({"ok": False, "error_code": 400, "description": "private-content"}, 200),
    ({"ok": True, "result": {"message_id": 1}}, 500),
    ("not json", 502), ("not json", 200), ([], 200),
    ({"ok": True}, 200), ({"ok": True, "result": {"message_id": True}}, 200),
    ({"ok": "true", "result": {"message_id": 1}}, 200),
    ({"ok": False}, 302),
])
def test_errors_or_malformed_responses_are_not_success(client, body, status):
    sender, session = client
    session.post.return_value = response(body, status)
    with pytest.raises(TelegramError) as error:
        sender.send_message("Reminder")
    assert "private-content" not in str(error.value)
    session.post.assert_called_once()


@pytest.mark.parametrize("error_type", [requests.Timeout, requests.ConnectionError])
def test_transport_failures_are_sanitized_and_not_retried(client, error_type):
    sender, session = client
    session.post.side_effect = error_type("https://api.telegram.org/botfake-test-token/private")
    with pytest.raises(TelegramError) as error:
        sender.send_message("Reminder")
    assert "fake-test-token" not in str(error.value)
    assert error.value.__suppress_context__
    session.post.assert_called_once()


def test_rate_limit_prevents_requests_until_cooldown_expires(client, monkeypatch):
    sender, session = client
    monkeypatch.setattr("devpost_reminder.telegram.time.monotonic", lambda: 100)
    session.post.return_value = response({"ok": False, "parameters": {"retry_after": 30}}, 429)
    with pytest.raises(TelegramError) as error:
        sender.send_message("First")
    assert error.value.retry_after == 30
    with pytest.raises(TelegramError, match="cooldown"):
        sender.send_message("Second")
    assert session.post.call_count == 1
    monkeypatch.setattr("devpost_reminder.telegram.time.monotonic", lambda: 131)
    session.post.return_value = response({"ok": True, "result": {"message_id": 2}})
    sender.send_message("Third")
    assert session.post.call_count == 2


def test_rate_limit_without_valid_retry_after_uses_conservative_cooldown(client):
    sender, session = client
    session.post.return_value = response({"ok": False}, 429)
    with pytest.raises(TelegramError) as error:
        sender.send_message("Reminder")
    assert error.value.retry_after == 60
