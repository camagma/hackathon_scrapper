"""Run CLI delivery against fake Devpost data and fake Telegram responses."""

from contextlib import redirect_stdout
from datetime import date
import io
import json
from unittest.mock import Mock

import pytest
import requests

from devpost_reminder.fetch import FetchError
from devpost_reminder.cli import main
from devpost_reminder.storage import get_hackathon, open_database


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result._content_consumed = True
    return result


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    config = tmp_path / "devpost_reminder.config.toml"
    config.write_text('keywords = ["agent"]\n', encoding="utf-8")
    path = tmp_path / "bot.sqlite3"
    items = [{
        "id": 1, "title": "Agent challenge", "url": "https://example.com/",
        "submission_period_dates": "Nov 10 - 30, 2026", "themes": [], "prize_amount": "",
        "displayed_location": {"location": "Online"}, "open_state": "upcoming",
    }]
    fetch = Mock(return_value=items)
    post = Mock(return_value=response({"ok": True, "result": {"message_id": 1}}))
    monkeypatch.setattr("devpost_reminder.app.fetch_hackathons", fetch)
    monkeypatch.setattr("requests.Session.post", post)
    monkeypatch.setattr("devpost_reminder.app.current_date", lambda config: date(2026, 11, 3))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-cli-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    args = ["devpost_reminder.cli.py", "--config", str(config), "--db", str(path), "--send-reminders"]
    return args, path, items, fetch, post


def run_cli(monkeypatch, args):
    monkeypatch.setattr("sys.argv", args)
    output = io.StringIO()
    with redirect_stdout(output):
        code = main()
    return code, output.getvalue()


def test_sends_each_threshold_once_across_cli_runs(delivery, monkeypatch):
    args, path, _, _, post = delivery
    code, output = run_cli(monkeypatch, args)
    assert code == 0
    assert "1 sent, 0 failed" in output
    assert "Days until opening: 7" in post.call_args.kwargs["json"]["text"]
    assert run_cli(monkeypatch, args)[0] == 0
    assert post.call_count == 1
    monkeypatch.setattr("devpost_reminder.app.current_date", lambda config: date(2026, 11, 9))
    assert run_cli(monkeypatch, args)[0] == 0
    assert post.call_count == 2
    with open_database(path) as connection:
        event = get_hackathon(connection, 1)
        assert event.reminded_start_7d and event.reminded_start_1d


@pytest.mark.parametrize("failure", ["rejected", "timeout", "rate_limit"])
def test_failed_delivery_exits_nonzero_without_marking(delivery, monkeypatch, caplog, failure):
    args, path, _, _, post = delivery
    if failure == "timeout":
        post.side_effect = requests.Timeout("fake-cli-token must not be logged")
    elif failure == "rate_limit":
        post.return_value = response({"ok": False, "parameters": {"retry_after": 30}}, 429)
    else:
        post.return_value = response({"ok": False, "error_code": 400}, 400)
    code, output = run_cli(monkeypatch, args)
    assert code == 1
    assert "0 sent, 1 failed" in output
    assert "fake-cli-token" not in caplog.text + output
    with open_database(path) as connection:
        assert not get_hackathon(connection, 1).reminded_start_7d


def test_missing_credentials_fail_before_fetch_or_database_changes(delivery, monkeypatch):
    args, path, _, fetch, post = delivery
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert run_cli(monkeypatch, args)[0] == 1
    fetch.assert_not_called()
    post.assert_not_called()
    assert not path.exists()


def test_failed_fetch_never_sends(delivery, monkeypatch):
    args, path, _, fetch, post = delivery
    fetch.side_effect = FetchError("Incomplete fetch")
    assert run_cli(monkeypatch, args)[0] == 1
    post.assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize("extra", [
    ["--offline", "snapshot.json"], ["--preview-reminders"], ["--today", "2026-11-03"],
])
def test_send_cannot_use_snapshots_previews_or_date_overrides(delivery, monkeypatch, extra):
    args, path, _, fetch, post = delivery
    with pytest.raises(SystemExit) as error:
        run_cli(monkeypatch, args + extra)
    assert error.value.code == 2
    fetch.assert_not_called()
    post.assert_not_called()
    assert not path.exists()


def test_retry_sends_only_the_failed_event(delivery, monkeypatch):
    args, path, items, _, post = delivery
    items.append({**items[0], "id": 2, "title": "Another agent challenge"})
    post.side_effect = [response({"ok": True, "result": {"message_id": 1}}),
                        response({"ok": False}, 400)]
    assert run_cli(monkeypatch, args)[0] == 1
    with open_database(path) as connection:
        assert get_hackathon(connection, 1).reminded_start_7d
        assert not get_hackathon(connection, 2).reminded_start_7d
    post.side_effect = None
    post.return_value = response({"ok": True, "result": {"message_id": 2}})
    assert run_cli(monkeypatch, args)[0] == 0
    assert post.call_count == 3
    assert post.call_args.kwargs["json"]["text"].startswith("Another agent challenge")


def test_plain_listing_does_not_require_credentials_or_send(delivery, monkeypatch):
    args, _, _, _, post = delivery
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    assert run_cli(monkeypatch, [arg for arg in args if arg != "--send-reminders"])[0] == 0
    post.assert_not_called()
