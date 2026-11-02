"""Verify independent reminder flags and explicit transaction boundaries."""

from dataclasses import replace
from datetime import date

import pytest

from storage import Hackathon, get_hackathon, mark_reminded, open_database, upsert_hackathons


@pytest.fixture
def database(tmp_path):
    with open_database(tmp_path / "bot.sqlite3") as connection:
        event = Hackathon(
            id=1, title="Challenge", url="https://example.com/",
            start_date=date(2026, 11, 1), deadline=date(2026, 11, 10),
            submission_period="Nov 01 - 10, 2026", themes=(), prize="",
            open_state="open", location="Online", organization_name="Example",
        )
        upsert_hackathons(connection, [event])
        yield connection


def test_flags_are_independent_and_setting_twice_is_a_noop(database):
    with database:
        database.execute("BEGIN IMMEDIATE")
        assert mark_reminded(database, 1, 7)
        assert not mark_reminded(database, 1, 7)
    event = get_hackathon(database, 1)
    assert event.reminded_7d and not event.reminded_1d
    with database:
        database.execute("BEGIN IMMEDIATE")
        assert mark_reminded(database, 1, 1)
    assert get_hackathon(database, 1).reminded_1d


def test_flag_update_can_be_rolled_back(database):
    with pytest.raises(RuntimeError, match="Simulated"):
        with database:
            database.execute("BEGIN IMMEDIATE")
            mark_reminded(database, 1, 7)
            raise RuntimeError("Simulated failure")
    assert not get_hackathon(database, 1).reminded_7d


@pytest.mark.parametrize("days", [0, 2, 8, True, "7"])
def test_invalid_thresholds_do_not_change_flags(database, days):
    with pytest.raises(ValueError, match="threshold"):
        mark_reminded(database, 1, days)
    assert not get_hackathon(database, 1).reminded_7d


def test_flags_require_an_explicit_transaction(database):
    with pytest.raises(RuntimeError, match="transaction"):
        mark_reminded(database, 1, 7)


def test_unknown_event_is_not_marked(database):
    assert get_hackathon(database, 999) is None
    with database:
        database.execute("BEGIN IMMEDIATE")
        assert not mark_reminded(database, 999, 7)
