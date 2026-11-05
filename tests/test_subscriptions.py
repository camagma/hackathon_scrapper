"""Check durable subscriptions, isolated reminder history, and update rollback."""

from contextlib import closing
import sqlite3

import pytest

from devpost_reminder.storage import open_database, SCHEMA, EXPORT_SCHEMA
from devpost_reminder.subscriptions import (
    advance_update_offset, read_update_offset, set_subscription, subscribed_ids,
)


def seed(connection):
    with connection:
        connection.execute("""INSERT INTO hackathons (
            id, title, url, start_date, deadline, submission_period, themes, prize,
            open_state, location, organization_name
        ) VALUES (1, 'Example', 'https://example.com', '2027-01-08', '2027-01-10',
                  'Jan 8 - 10, 2027', '[]', '', 'upcoming', 'Online', '')""")


def test_membership_is_idempotent_and_chat_specific(tmp_path):
    path = tmp_path / "state.sqlite3"
    with open_database(path) as db:
        seed(db)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for _ in range(2):
                set_subscription(db, 101, 1, active=True)
            set_subscription(db, -202, 1, active=True)
            set_subscription(db, 101, 1, active=False)
        assert subscribed_ids(db, 101) == ()
        assert subscribed_ids(db, -202) == (1,)
        assert db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 2
    with open_database(path) as db:
        assert subscribed_ids(db, -202) == (1,)


def test_resubscription_preserves_only_that_chats_flags(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as db:
        seed(db)
        with db:
            db.execute("BEGIN IMMEDIATE")
            set_subscription(db, 101, 1, active=True)
            db.execute("UPDATE subscriptions SET reminded_7d = 1 WHERE chat_id = 101")
            set_subscription(db, 101, 1, active=False)
            set_subscription(db, 101, 1, active=True)
            set_subscription(db, 202, 1, active=True)
        assert [tuple(row) for row in db.execute(
            "SELECT chat_id, reminded_7d, reminded_1d FROM subscriptions ORDER BY chat_id"
        )] == [(101, 1, 0), (202, 0, 0)]


def test_cursor_and_membership_rollback_together(tmp_path):
    path = tmp_path / "state.sqlite3"
    with open_database(path) as db:
        seed(db)
        assert read_update_offset(db) == 0
        with pytest.raises(RuntimeError, match="Interrupted"):
            with db:
                db.execute("BEGIN IMMEDIATE")
                set_subscription(db, 101, 1, active=True)
                advance_update_offset(db, 42)
                raise RuntimeError("Interrupted")
        assert subscribed_ids(db, 101) == ()
        assert read_update_offset(db) == 0
        with db:
            db.execute("BEGIN IMMEDIATE")
            set_subscription(db, 101, 1, active=True)
            advance_update_offset(db, 42)
            advance_update_offset(db, 42)
    with open_database(path) as db:
        assert read_update_offset(db) == 42
        assert subscribed_ids(db, 101) == (1,)
        with pytest.raises(ValueError, match="backwards"):
            with db:
                db.execute("BEGIN IMMEDIATE")
                advance_update_offset(db, 41)


@pytest.mark.parametrize("offset", [-1, True, "42", 1.5])
def test_invalid_cursor_is_rejected(tmp_path, offset):
    with open_database(tmp_path / "state.sqlite3") as db:
        with pytest.raises(ValueError):
            with db:
                db.execute("BEGIN IMMEDIATE")
                advance_update_offset(db, offset)
        assert read_update_offset(db) == 0


def test_mutations_require_transaction_and_existing_event(tmp_path):
    with open_database(tmp_path / "state.sqlite3") as db:
        with pytest.raises(RuntimeError):
            set_subscription(db, 101, 1, active=True)
        with pytest.raises(RuntimeError):
            advance_update_offset(db, 1)
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                db.execute("BEGIN IMMEDIATE")
                set_subscription(db, 101, 999, active=True)


def test_version_three_upgrade_keeps_existing_history(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        with db:
            db.execute(SCHEMA)
            db.execute(EXPORT_SCHEMA)
            for column in ("reminded_start_7d", "reminded_start_1d"):
                db.execute(f"ALTER TABLE hackathons ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
            seed(db)
            db.execute("UPDATE hackathons SET reminded_start_7d = 1")
            db.execute("INSERT INTO export_state VALUES (1, '2026-11-03', '[1]')")
            db.execute("PRAGMA user_version = 3")
    for _ in range(2):
        with open_database(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert db.execute("SELECT reminded_start_7d FROM hackathons").fetchone()[0] == 1
            assert db.execute("SELECT event_ids FROM export_state").fetchone()[0] == '[1]'
            assert subscribed_ids(db, 101) == ()
            assert read_update_offset(db) == 0
