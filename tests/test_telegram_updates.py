"""Validate bounded update polling with fake Telegram responses only."""

import json
from unittest.mock import Mock

import pytest
import requests

from devpost_reminder.telegram import TelegramClient, TelegramCredentials, TelegramError


def client_with(body, status=200, timeout=(10, 30)):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response._content_consumed = True
    session = Mock()
    session.post.return_value = response
    return TelegramClient(TelegramCredentials("fake-token", "123"), session, timeout=timeout), session


def test_fetches_one_batch_without_acknowledging_it():
    updates = [{"update_id": 42, "callback_query": {"data": "follow:1"}}, {"update_id": 45}]
    client, session = client_with({"ok": True, "result": updates})
    assert client.get_updates(42, limit=10) == updates
    session.post.assert_called_once_with(
        "https://api.telegram.org/botfake-token/getUpdates",
        json={"offset": 42, "limit": 10, "timeout": 5, "allowed_updates": ["message", "callback_query"]},
        timeout=(10, 30), allow_redirects=False,
    )


def test_empty_queue_and_read_timeout_exceeds_poll_wait():
    client, session = client_with({"ok": True, "result": []}, timeout=(1, 2))
    assert client.get_updates() == []
    assert session.post.call_args.kwargs["timeout"] == (1, 10)


@pytest.mark.parametrize("offset,limit", [(-1, 100), (True, 100), ("1", 100), (0, 0),
                                         (0, 101), (0, True), (0, 1.5)])
def test_invalid_arguments_never_request(offset, limit):
    client, session = client_with({"ok": True, "result": []})
    with pytest.raises(ValueError):
        client.get_updates(offset, limit=limit)
    session.post.assert_not_called()


@pytest.mark.parametrize("result", [None, {}, [None], [{}], [{"update_id": True}],
    [{"update_id": 0}], [{"update_id": 2}, {"update_id": 2}],
    [{"update_id": 3}, {"update_id": 2}], [{"update_id": "2"}]])
def test_malformed_batch_is_rejected_as_a_whole(result):
    client, _ = client_with({"ok": True, "result": result})
    with pytest.raises(TelegramError):
        client.get_updates(1)


def test_oversized_batch_is_rejected():
    client, _ = client_with({"ok": True, "result": [{"update_id": 1}, {"update_id": 2}]})
    with pytest.raises(TelegramError):
        client.get_updates(limit=1)


def test_rate_limit_cooldown_is_shared_with_delivery():
    client, session = client_with({"ok": False, "parameters": {"retry_after": 30}}, 429)
    with pytest.raises(TelegramError) as error:
        client.get_updates()
    assert error.value.retry_after == 30
    with pytest.raises(TelegramError, match="cooldown"):
        client.send_message("Hello")
    assert session.post.call_count == 1


def test_transport_error_is_sanitized_without_retry():
    client, session = client_with({"ok": True, "result": []})
    session.post.side_effect = requests.Timeout("private-token-and-chat-data")
    with pytest.raises(TelegramError) as error:
        client.get_updates()
    assert "private-token-and-chat-data" not in str(error.value)
    session.post.assert_called_once()


def test_webhook_conflict_is_reported_without_deleting_webhook():
    client, session = client_with({"ok": False, "error_code": 409}, 409)
    with pytest.raises(TelegramError) as error:
        client.get_updates()
    assert error.value.status_code == 409
    session.post.assert_called_once()
