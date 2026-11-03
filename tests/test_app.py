"""Exercise the application without CLI arguments or console output."""

from datetime import date
import json
from unittest.mock import Mock

import pytest

from devpost_reminder.app import run
from devpost_reminder.config import Config
from devpost_reminder.storage import list_hackathons, open_database


def test_programmatic_preview_returns_results_without_printing(tmp_path, capsys):
    snapshot = tmp_path / "events.json"
    item = {
        "id": 1, "title": "Agent challenge", "url": "https://example.com/",
        "submission_period_dates": "Nov 10 - 30, 2026", "themes": [],
        "prize_amount": "$<span>100</span>", "open_state": "upcoming",
        "displayed_location": {"location": "Online"},
    }
    snapshot.write_text(json.dumps({"hackathons": [item], "meta": {"total_count": 1, "per_page": 40}}))
    path = tmp_path / "state.sqlite3"
    config = Config(database_path=path)
    result = run(config, mode="preview", offline=snapshot, today=date(2026, 11, 3))
    assert result.sync.inserted == 1
    assert result.fetched_count == 1
    assert result.events[0].prize == "$100"
    assert result.preview[0].days_left == 7
    assert result.delivery is None
    assert capsys.readouterr().out == ""
    with open_database(path) as connection:
        assert not list_hackathons(connection)[0].reminded_start_7d
    repeated = run(config, offline=snapshot)
    assert repeated.sync.inserted == 0
    assert repeated.sync.refreshed == 1
    assert repeated.preview == ()


@pytest.mark.parametrize("options", [
    {"mode": "unknown"}, {"mode": "send", "offline": "events.json"},
    {"mode": "send", "today": date(2026, 11, 3)},
    {"mode": "list", "today": date(2026, 11, 3)},
])
def test_invalid_programmatic_modes_fail_before_side_effects(tmp_path, monkeypatch, options):
    fetch = Mock(side_effect=AssertionError("Fetch should not run"))
    credentials = Mock(side_effect=AssertionError("Credentials should not be read"))
    monkeypatch.setattr("devpost_reminder.app.fetch_hackathons", fetch)
    monkeypatch.setattr("devpost_reminder.app.load_telegram_credentials", credentials)
    path = tmp_path / "state.sqlite3"
    with pytest.raises(ValueError):
        run(Config(database_path=path), **options)
    fetch.assert_not_called()
    credentials.assert_not_called()
    assert not path.exists()
