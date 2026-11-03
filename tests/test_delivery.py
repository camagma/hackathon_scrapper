"""Test durable deduplication, sender failures, and concurrent dispatchers."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier
from unittest.mock import Mock

import pytest

from devpost_reminder.config import Config
import devpost_reminder.reminders as reminders
from devpost_reminder.reminders import deliver_reminders
from devpost_reminder.storage import Hackathon, get_hackathon, open_database, upsert_hackathons


TODAY = date(2026, 11, 3)


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "state.sqlite3"
    event = Hackathon(
        id=1, title="Agent Challenge", url="https://example.com/",
        start_date=date(2026, 11, 1), deadline=date(2026, 11, 10),
        submission_period="Nov 01 - 10, 2026", themes=(), prize="",
        open_state="open", location="Online", organization_name="Example",
    )
    with open_database(path) as connection:
        upsert_hackathons(connection, [event], complete_snapshot=True)
    return path, event


def test_each_reminder_sent_once_across_reopens_and_syncs(state):
    path, event = state
    sender = Mock()
    for today, expected in [(TODAY, 1), (TODAY, 0), (date(2026, 11, 9), 1), (date(2026, 11, 9), 0)]:
        with open_database(path) as connection:
            upsert_hackathons(connection, [event], complete_snapshot=True)
            assert deliver_reminders(connection, Config(), sender, today=today).sent == expected
    assert sender.call_count == 2
    with open_database(path) as connection:
        event = get_hackathon(connection, 1)
        assert event.reminded_7d and event.reminded_1d


def test_failed_send_keeps_flag_unset_and_can_retry_same_day(state, caplog):
    path, _ = state
    failed = Mock(side_effect=RuntimeError("credential-bearing-url-must-not-be-logged"))
    with open_database(path) as connection:
        result = deliver_reminders(connection, Config(), failed, today=TODAY)
        assert (result.sent, result.failed) == (0, 1)
        assert not get_hackathon(connection, 1).reminded_7d
    assert "credential-bearing-url" not in caplog.text
    with open_database(path) as connection:
        sender = Mock()
        assert deliver_reminders(connection, Config(), sender, today=TODAY).sent == 1
        sender.assert_called_once()


def test_later_failure_does_not_undo_earlier_success(state):
    path, event = state
    with open_database(path) as connection:
        upsert_hackathons(connection, [replace(event, id=2)])
        sender = Mock(side_effect=[None, RuntimeError("Rejected")])
        result = deliver_reminders(connection, Config(), sender, today=TODAY)
        assert (result.sent, result.failed) == (1, 1)
        assert get_hackathon(connection, 1).reminded_7d
        assert not get_hackathon(connection, 2).reminded_7d
    with open_database(path) as connection:
        sender = Mock()
        assert deliver_reminders(connection, Config(), sender, today=TODAY).sent == 1
        sender.assert_called_once()


@pytest.mark.parametrize("change", [
    "reminded_7d = 1", "is_current = 0", "title = 'Other challenge'", "deadline = '2026-11-11'",
])
def test_candidate_is_rechecked_after_another_writer_changes_it(state, monkeypatch, change):
    path, _ = state
    select = reminders.pending_reminders

    def select_then_modify(*args):
        candidates = select(*args)
        with open_database(path) as writer:
            with writer:
                writer.execute(f"UPDATE hackathons SET {change} WHERE id = 1")
        return candidates

    monkeypatch.setattr(reminders, "pending_reminders", select_then_modify)
    with open_database(path) as connection:
        sender = Mock()
        result = deliver_reminders(connection, Config(keywords=("agent",)), sender, today=TODAY)
        assert (result.sent, result.skipped) == (0, 1)
        sender.assert_not_called()


def test_overlapping_dispatchers_send_only_once(state, monkeypatch):
    path, _ = state
    barrier = Barrier(2)
    select = reminders.pending_reminders
    messages = []

    def select_together(*args):
        candidates = select(*args)
        assert len(candidates) == 1
        barrier.wait(timeout=10)
        return candidates

    def worker():
        with open_database(path) as connection:
            return deliver_reminders(connection, Config(), messages.append, today=TODAY)

    monkeypatch.setattr(reminders, "pending_reminders", select_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert len(messages) == 1
    assert sum(result.sent for result in results) == 1
    assert sum(result.skipped for result in results) == 1
