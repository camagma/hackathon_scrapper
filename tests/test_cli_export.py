"""Verify live-mode CSV delivery end to end with fake HTTP and Devpost data."""

from contextlib import redirect_stdout
from datetime import date
import io
import json
from unittest.mock import Mock

import pytest
import requests

from devpost_reminder.cli import main
from devpost_reminder.storage import get_hackathon, open_database, read_export_state


def response(body=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body if body is not None else {"ok": True, "result": {"message_id": 1}}).encode()
    result._content_consumed = True
    return result


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    settings = tmp_path / "config.toml"
    settings.write_text('[export]\nmode = "daily"\n', encoding="utf-8")
    path = tmp_path / "bot.sqlite3"
    event = {"id": 1, "title": "Agent challenge", "url": "https://example.com/",
             "submission_period_dates": "Nov 10 - 30, 2026", "themes": [], "prize_amount": "",
             "displayed_location": {"location": "Online"}, "open_state": "upcoming"}
    items = [event, {**event, "id": 2, "open_state": "open", "submission_period_dates": "Nov 01 - 20, 2026"}]
    fetch = Mock(return_value=items)
    post = Mock(return_value=response())
    monkeypatch.setattr("devpost_reminder.app.fetch_hackathons", fetch)
    monkeypatch.setattr("requests.Session.post", post)
    monkeypatch.setattr("devpost_reminder.app.current_date", lambda config: date(2026, 11, 3))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-export-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    args = ["devpost_reminder", "--config", str(settings), "--db", str(path)]
    return args, path, settings, items, fetch, post


def run_cli(monkeypatch, args):
    monkeypatch.setattr("sys.argv", args)
    output = io.StringIO()
    with redirect_stdout(output):
        code = main()
    return code, output.getvalue()


def test_reminders_and_export_send_once_with_separate_state(delivery, monkeypatch):
    args, path, _, _, _, post = delivery
    args += ["--send-reminders", "--send-export"]
    code, output = run_cli(monkeypatch, args)
    assert code == 0 and "1 sent, 0 failed" in output
    assert "CSV export: sent (2 hackathons)" in output
    assert [call.args[0].rsplit("/", 1)[-1] for call in post.call_args_list] == ["sendMessage", "sendDocument"]
    assert post.call_args.kwargs["files"]["document"][1].closed
    with open_database(path) as connection:
        assert get_hackathon(connection, 1).reminded_start_7d
        assert not get_hackathon(connection, 2).reminded_start_7d
        assert read_export_state(connection).event_ids == frozenset({1, 2})
    code, output = run_cli(monkeypatch, args)
    assert code == 0 and "CSV export: skipped" in output
    assert post.call_count == 2


def test_export_can_run_without_reminders(delivery, monkeypatch):
    args, path, _, _, _, post = delivery
    code, output = run_cli(monkeypatch, args + ["--send-export"])
    assert code == 0 and "CSV export: sent" in output
    post.assert_called_once()
    assert post.call_args.args[0].endswith("/sendDocument")
    with open_database(path) as connection:
        assert not get_hackathon(connection, 1).reminded_start_7d


def test_failed_export_retains_reminders_and_retries_only_csv(delivery, monkeypatch, caplog):
    args, path, _, _, _, post = delivery
    args += ["--send-reminders", "--send-export"]

    def upload_failure(url, **kwargs):
        if url.endswith("/sendDocument"):
            raise requests.Timeout("fake-export-token must not be logged")
        return response()

    post.side_effect = upload_failure
    code, output = run_cli(monkeypatch, args)
    assert code == 1 and "1 sent, 0 failed" in output
    assert "CSV export: failed" in output
    assert "fake-export-token" not in output + caplog.text
    with open_database(path) as connection:
        assert get_hackathon(connection, 1).reminded_start_7d
        assert read_export_state(connection).last_success is None
    post.side_effect = None
    code, output = run_cli(monkeypatch, args)
    assert code == 0 and "0 sent, 0 failed" in output
    assert "CSV export: sent" in output
    assert post.call_count == 3


def test_failed_reminder_does_not_skip_csv(delivery, monkeypatch):
    args, path, _, _, _, post = delivery
    post.side_effect = [response({"ok": False}, 400), response()]
    code, output = run_cli(monkeypatch, args + ["--send-reminders", "--send-export"])
    assert code == 1 and "0 sent, 1 failed" in output
    assert "CSV export: sent" in output
    with open_database(path) as connection:
        assert not get_hackathon(connection, 1).reminded_start_7d
        assert read_export_state(connection).last_success == date(2026, 11, 3)


def test_empty_result_sends_one_text_instead_of_document(delivery, monkeypatch):
    args, path, settings, _, _, post = delivery
    settings.write_text('keywords = ["no-match"]\n[export]\nmode = "daily"\n', encoding="utf-8")
    code, output = run_cli(monkeypatch, args + ["--send-export"])
    assert code == 0 and "CSV export: empty (0 hackathons)" in output
    post.assert_called_once()
    assert post.call_args.kwargs["json"]["text"] == "No hackathons match your current filters."
    assert run_cli(monkeypatch, args + ["--send-export"])[0] == 0
    assert post.call_count == 1


def test_default_weekly_schedule_does_not_send_on_tuesday(delivery, monkeypatch):
    args, _, settings, _, _, post = delivery
    settings.write_text("", encoding="utf-8")
    code, output = run_cli(monkeypatch, args + ["--send-export"])
    assert code == 0 and "CSV export: skipped" in output
    post.assert_not_called()


def test_missing_credentials_stop_export_before_fetch(delivery, monkeypatch):
    args, path, _, _, fetch, post = delivery
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert run_cli(monkeypatch, args + ["--send-export"])[0] == 1
    fetch.assert_not_called()
    post.assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize("extra", [["--offline", "snapshot.json"], ["--preview-reminders"], ["--today", "2026-11-03"]])
def test_export_cannot_send_from_offline_or_preview_modes(delivery, monkeypatch, extra):
    args, path, _, _, fetch, post = delivery
    with pytest.raises(SystemExit) as error:
        run_cli(monkeypatch, args + ["--send-export", *extra])
    assert error.value.code == 2
    fetch.assert_not_called()
    post.assert_not_called()
    assert not path.exists()
