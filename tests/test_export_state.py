"""Check durable export history and safe migration from schema version one."""

from contextlib import closing
from datetime import date
import sqlite3

import pytest

from devpost_reminder.config import ExportConfig
from devpost_reminder.export import export_due
from devpost_reminder.storage import (
    SCHEMA, ExportState, get_hackathon, open_database, read_export_state, record_export_success,
)


DAY = date(2026, 11, 3)


def record(connection, day=DAY, ids=(1, 2)):
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        record_export_success(connection, day, ids)


def test_first_read_is_empty_and_does_not_create_success_row(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        state = read_export_state(connection)
        assert state == ExportState()
        assert not state.has_new([])
        assert state.has_new([1])
        assert connection.execute("SELECT COUNT(*) FROM export_state").fetchone()[0] == 0


def test_success_survives_reopening_and_deduplicates_ids(tmp_path):
    path = tmp_path / "state.sqlite3"
    with open_database(path) as connection:
        record(connection, ids=[2, 1, 2])
    with open_database(path) as connection:
        state = read_export_state(connection)
        assert state == ExportState(DAY, frozenset({1, 2}))
        assert not state.has_new([1, 2])
        assert state.has_new([1, 2, 3])


def test_failed_transaction_keeps_previous_success(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        record(connection)
        with pytest.raises(RuntimeError, match="Upload failed"):
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                record_export_success(connection, date(2026, 11, 4), [3])
                raise RuntimeError("Upload failed")
        assert read_export_state(connection) == ExportState(DAY, frozenset({1, 2}))


def test_empty_selection_can_record_confirmed_text_delivery(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        record(connection, ids=[])
        state = read_export_state(connection)
        assert state == ExportState(DAY)
        assert not export_due(ExportConfig(mode="daily"), DAY, state.last_success)
        assert state.has_new([1])


def test_same_day_new_event_export_replaces_previous_snapshot(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        record(connection)
        record(connection, ids=[2, 3])
        state = read_export_state(connection)
        assert state.event_ids == frozenset({2, 3})
        assert state.has_new([1, 2, 3])


def test_success_cannot_be_recorded_outside_transaction(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        with pytest.raises(RuntimeError, match="transaction"):
            record_export_success(connection, DAY, [1])
        assert read_export_state(connection) == ExportState()


@pytest.mark.parametrize("ids", [[True], ["1"], [1.0]])
def test_invalid_ids_do_not_change_previous_state(tmp_path, ids):
    with open_database(tmp_path / "state.sqlite3") as connection:
        record(connection)
        with pytest.raises(ValueError, match="integers"):
            record(connection, ids=ids)
        assert read_export_state(connection) == ExportState(DAY, frozenset({1, 2}))


def test_history_date_cannot_move_backwards(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        record(connection)
        with pytest.raises(ValueError, match="backwards"):
            record(connection, date(2026, 11, 2), [])
        assert read_export_state(connection).last_success == DAY


def test_version_one_migrates_without_losing_reminders(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute(SCHEMA)
            connection.execute("PRAGMA user_version = 1")
            connection.execute("""INSERT INTO hackathons (
                id, title, url, start_date, deadline, submission_period, themes, prize,
                open_state, location, organization_name, reminded_7d, reminded_1d
            ) VALUES (1, 'Legacy event', 'https://example.com/', '2026-11-01', '2026-11-10',
                      'Nov 01 - 10, 2026', '[]', '', 'open', 'Online', 'Example', 1, 1)""")
    for _ in range(2):
        with open_database(path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
            event = get_hackathon(connection, 1)
            assert event.title == "Legacy event" and event.reminded_7d and event.reminded_1d
            assert read_export_state(connection) == ExportState()


def test_migration_failure_does_not_advance_version(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE export_state (conflicting_column INTEGER)")
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(sqlite3.OperationalError):
        with open_database(path):
            pytest.fail("Conflicting schema should not open")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA table_info(export_state)").fetchone()[1] == "conflicting_column"
