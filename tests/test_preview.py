"""Ensure reminder previews never send or mark reminder flags."""

from contextlib import redirect_stdout
from datetime import date
import io
import json
from unittest.mock import Mock

import pytest

from devpost_reminder.config import Config
from devpost_reminder.cli import main
from devpost_reminder.reminders import deliver_reminders
from devpost_reminder.storage import get_hackathon, open_database


@pytest.fixture
def preview_args(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "hackathons": [{
            "id": 1, "title": "AI Challenge", "url": "https://example.com/",
            "submission_period_dates": "Nov 01 - 10, 2026", "prize_amount": "",
            "themes": [], "displayed_location": {"location": "Online"}, "open_state": "open",
        }], "meta": {"total_count": 1, "per_page": 40},
    }), encoding="utf-8")
    config = tmp_path / "devpost_reminder.config.toml"
    config.write_text('timezone = "Etc/GMT-2"\n', encoding="utf-8")
    database = tmp_path / "preview.sqlite3"
    args = ["devpost_reminder.cli.py", "--config", str(config), "--offline", str(snapshot), "--db", str(database),
            "--preview-reminders", "--today", "2026-11-03"]
    return args, database


def run_preview(monkeypatch, args):
    monkeypatch.setattr("sys.argv", args)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main() == 0
    return output.getvalue()


def test_repeated_previews_leave_flags_unset(preview_args, monkeypatch):
    args, path = preview_args
    monkeypatch.setattr("requests.Session", Mock(side_effect=AssertionError("Network is forbidden")))
    for _ in range(2):
        output = run_preview(monkeypatch, args)
        assert "2026-11-03 (Etc/GMT-2): 1 pending" in output
        assert "Осталось дней: 7" in output
        with open_database(path) as connection:
            event = get_hackathon(connection, 1)
            assert not event.reminded_7d and not event.reminded_1d


def test_preview_uses_stored_flags_after_a_successful_send(preview_args, monkeypatch):
    args, path = preview_args
    run_preview(monkeypatch, args)
    with open_database(path) as connection:
        assert deliver_reminders(connection, Config(), Mock(), today=date(2026, 11, 3)).sent == 1
    assert "0 pending" in run_preview(monkeypatch, args)


def test_date_override_requires_preview(preview_args, monkeypatch):
    args, path = preview_args
    args.remove("--preview-reminders")
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert not path.exists()
