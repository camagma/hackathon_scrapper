"""Check scheduled CSV delivery, empty selections, retries, and isolated errors."""

from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from devpost_reminder.config import Config, ExportConfig
from devpost_reminder.export import deliver_export
from devpost_reminder.reminders import deliver_reminders
from devpost_reminder.storage import (
    ExportState, Hackathon, get_hackathon, open_database, read_export_state, upsert_hackathons,
)


TODAY = date(2026, 11, 3)


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "bot.sqlite3"
    event = Hackathon(
        id=1, title="Agent challenge", url="https://example.com/",
        start_date=date(2026, 11, 10), deadline=date(2026, 11, 30),
        submission_period="Nov 10 - 30, 2026", themes=(), prize="$100",
        open_state="upcoming", location="Online", organization_name="Example",
    )
    with open_database(path) as connection:
        upsert_hackathons(connection, [event], complete_snapshot=True)
    return path, event


def config(mode="daily", **kwargs):
    return Config(export=ExportConfig(mode=mode), **kwargs)


def test_document_is_available_during_send_and_success_commits_afterward(state):
    path, _ = state
    sent_paths = []
    with open_database(path) as connection:
        def upload(csv_path, caption):
            sent_paths.append(csv_path)
            assert read_export_state(connection) == ExportState()
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                assert [row["id"] for row in csv.DictReader(source)] == ["1"]
            assert "Hackathons in this file: 1" in caption
            assert "2026-11-30" in caption

        message = Mock()
        result = deliver_export(connection, config(), upload, message, today=TODAY)
        assert (result.status, result.count) == ("sent", 1)
        message.assert_not_called()
        event = get_hackathon(connection, 1)
        assert not event.reminded_start_7d and not event.reminded_start_1d
    assert not sent_paths[0].parent.exists()
    with open_database(path) as connection:
        assert read_export_state(connection) == ExportState(TODAY, frozenset({1}))
        upload = Mock()
        assert deliver_export(connection, config(), upload, Mock(), today=TODAY).status == "skipped"
        upload.assert_not_called()


def test_empty_selection_sends_text_once_without_a_document(state):
    path, _ = state
    with open_database(path) as connection:
        upload, message = Mock(), Mock()
        settings = config(keywords=("no-match",))
        result = deliver_export(connection, settings, upload, message, today=TODAY)
        assert result.status == "empty" and result.count == 0
        upload.assert_not_called()
        message.assert_called_once_with("No hackathons match your current filters.")
        assert read_export_state(connection) == ExportState(TODAY)
        assert deliver_export(connection, settings, upload, message, today=TODAY).status == "skipped"
        assert message.call_count == 1


def test_failed_upload_keeps_history_and_does_not_stop_reminders(state, caplog):
    path, _ = state
    uploaded = []

    def rejected(csv_path, caption):
        uploaded.append(csv_path)
        raise RuntimeError("secret-url-must-not-be-logged")

    with open_database(path) as connection:
        assert deliver_export(connection, config(), rejected, Mock(), today=TODAY).status == "failed"
        assert read_export_state(connection) == ExportState()
        assert not connection.in_transaction
        reminders = Mock()
        assert deliver_reminders(connection, config(), reminders, today=TODAY).sent == 1
        assert get_hackathon(connection, 1).reminded_start_7d
        assert deliver_export(connection, config(), Mock(), Mock(), today=TODAY).status == "sent"
    assert not uploaded[0].parent.exists()
    assert "secret-url-must-not-be-logged" not in caplog.text


def test_failed_empty_text_does_not_record_success(state):
    path, _ = state
    with open_database(path) as connection:
        result = deliver_export(connection, config(keywords=("no-match",)), Mock(),
                                Mock(side_effect=RuntimeError("Rejected")), today=TODAY)
        assert result.status == "failed"
        assert read_export_state(connection) == ExportState()


def test_new_mode_sends_full_selection_only_when_new_matching_ids_appear(state):
    path, event = state
    with open_database(path) as connection:
        upload, message = Mock(), Mock()
        settings = config("new", keywords=("agent",))
        assert deliver_export(connection, settings, upload, message, today=TODAY).status == "sent"
        upsert_hackathons(connection, [replace(event, id=2, title="Unrelated")])
        assert deliver_export(connection, settings, upload, message, today=TODAY).status == "skipped"
        upsert_hackathons(connection, [replace(event, id=3)])
        result = deliver_export(connection, settings, upload, message, today=TODAY)
        assert result.status == "sent" and result.count == 2
        assert read_export_state(connection).event_ids == frozenset({1, 3})
        assert upload.call_count == 2


def test_new_mode_with_no_matching_events_does_not_notify(state):
    path, _ = state
    with open_database(path) as connection:
        upload, message = Mock(), Mock()
        result = deliver_export(connection, config("new", keywords=("no-match",)), upload, message, today=TODAY)
        assert result.status == "skipped"
        upload.assert_not_called()
        message.assert_not_called()


def test_weekly_schedule_skips_other_weekdays(state):
    path, _ = state
    with open_database(path) as connection:
        upload = Mock()
        assert deliver_export(connection, Config(), upload, Mock(), today=TODAY).status == "skipped"
        upload.assert_not_called()
        assert deliver_export(connection, Config(), upload, Mock(), today=date(2026, 11, 9)).status == "sent"
        assert deliver_export(connection, Config(), upload, Mock(), today=date(2026, 11, 9)).status == "skipped"
        assert upload.call_count == 1


def test_overlapping_exports_share_success_state(state):
    path, _ = state
    upload, message = Mock(), Mock()

    def worker():
        with open_database(path) as connection:
            return deliver_export(connection, config(), upload, message, today=TODAY)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(result.status for result in results) == ["sent", "skipped"]
    upload.assert_called_once()
