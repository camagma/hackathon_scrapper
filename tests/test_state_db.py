"""Exercise state transfers against disposable local Git repositories only."""

from datetime import date
from pathlib import Path
import sqlite3
import subprocess

import pytest

from devpost_reminder.storage import Hackathon, get_hackathon, open_database, upsert_hackathons
from scripts.state_db import StateError, restore, save


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=data,
                          check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(checkout)], check=True, capture_output=True)
    git(checkout, "config", "user.name", "Test")
    git(checkout, "config", "user.email", "test@example.invalid")
    (checkout / "app.txt").write_text("Application source stays on main\n")
    git(checkout, "add", "app.txt")
    git(checkout, "commit", "-m", "Initial test application")
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "origin", "main")
    return checkout


def seed(database, *, reminded_7d=False, reminded_1d=False):
    event = Hackathon(
        id=1, title="Example", url="https://example.com/", start_date=date(2026, 11, 1),
        deadline=date(2026, 11, 10), submission_period="Nov 01 - 10, 2026", themes=(),
        prize="", open_state="open", location="Online", organization_name="Example",
    )
    with open_database(database) as connection:
        upsert_hackathons(connection, [event])
        with connection:
            connection.execute("UPDATE hackathons SET reminded_7d = ?, reminded_1d = ?",
                               (reminded_7d, reminded_1d))


def test_round_trip_preserves_flags_without_touching_main(repo, tmp_path):
    database = tmp_path / "first" / "bot.sqlite3"
    original_head = git(repo, "rev-parse", "HEAD")
    restore(repo, database)
    assert not database.exists()
    seed(database, reminded_7d=True)
    assert save(repo, database)
    assert git(repo, "rev-parse", "HEAD") == original_head
    assert git(repo, "status", "--porcelain") == ""
    restored = tmp_path / "second" / "bot.sqlite3"
    restore(repo, restored)
    assert git(repo, "ls-tree", "--name-only", "refs/remotes/origin/bot-state") == "hackathons.sqlite3"
    with open_database(restored) as connection:
        event = get_hackathon(connection, 1)
        assert event.reminded_7d and not event.reminded_1d
    assert not save(repo, restored)


def test_unchanged_database_does_not_create_another_commit(repo, tmp_path):
    database = tmp_path / "bot.sqlite3"
    restore(repo, database)
    seed(database)
    assert save(repo, database)
    revision = git(repo, "ls-remote", "origin", "refs/heads/bot-state")
    assert not save(repo, database)
    assert git(repo, "ls-remote", "origin", "refs/heads/bot-state") == revision


def test_restore_refuses_to_replace_local_state(repo, tmp_path):
    database = tmp_path / "bot.sqlite3"
    seed(database, reminded_7d=True)
    before = database.read_bytes()
    with pytest.raises(StateError, match="fresh destination"):
        restore(repo, database)
    assert database.read_bytes() == before


def test_remote_failure_is_not_treated_as_first_run(repo, tmp_path):
    git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    database = tmp_path / "bot.sqlite3"
    with pytest.raises(StateError):
        restore(repo, database)
    assert not database.exists()
    assert not database.with_name(database.name + ".state-revision").exists()


def test_existing_branch_without_database_is_not_reset(repo, tmp_path):
    git(repo, "push", "origin", "HEAD:refs/heads/bot-state")
    database = tmp_path / "bot.sqlite3"
    with pytest.raises(StateError):
        restore(repo, database)
    assert not database.exists()


def test_save_requires_restore_marker(repo, tmp_path):
    database = tmp_path / "bot.sqlite3"
    seed(database)
    with pytest.raises(FileNotFoundError):
        save(repo, database)
    assert git(repo, "ls-remote", "origin", "refs/heads/bot-state") == ""


def test_stale_writer_cannot_overwrite_newer_state(repo, tmp_path):
    original = tmp_path / "original.sqlite3"
    restore(repo, original)
    seed(original)
    save(repo, original)
    first, second = tmp_path / "first.sqlite3", tmp_path / "second.sqlite3"
    restore(repo, first)
    restore(repo, second)
    seed(first, reminded_7d=True)
    save(repo, first)
    seed(second, reminded_1d=True)
    with pytest.raises(StateError, match="push"):
        save(repo, second)
    latest = tmp_path / "latest.sqlite3"
    restore(repo, latest)
    with open_database(latest) as connection:
        event = get_hackathon(connection, 1)
        assert event.reminded_7d and not event.reminded_1d


def test_corrupt_remote_database_prevents_restore(repo, tmp_path):
    database = tmp_path / "original.sqlite3"
    restore(repo, database)
    seed(database)
    save(repo, database)
    parent = git(repo, "ls-remote", "origin", "refs/heads/bot-state").split()[0]
    blob = git(repo, "hash-object", "-w", "--stdin", data=b"not a SQLite database")
    tree = git(repo, "mktree", data=f"100644 blob {blob}\thackathons.sqlite3\n".encode())
    commit = git(repo, "commit-tree", tree, "-p", parent, data=b"Corrupt test state\n")
    git(repo, "push", "origin", f"{commit}:refs/heads/bot-state")
    target = tmp_path / "restored.sqlite3"
    with pytest.raises(sqlite3.DatabaseError):
        restore(repo, target)
    assert not target.exists()
    assert not target.with_name(target.name + ".state-revision").exists()


def test_backup_includes_committed_wal_data(repo, tmp_path):
    database = tmp_path / "source.sqlite3"
    restore(repo, database)
    seed(database)
    with open_database(database) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        with connection:
            connection.execute("UPDATE hackathons SET reminded_7d = 1")
        assert Path(str(database) + "-wal").exists()
        save(repo, database)
    target = tmp_path / "restored.sqlite3"
    restore(repo, target)
    with open_database(target) as connection:
        assert get_hackathon(connection, 1).reminded_7d
