"""Restore and save a runner's SQLite database on the bot-state Git branch."""

import argparse
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import subprocess
from tempfile import TemporaryDirectory


STATE_REF = "refs/heads/bot-state"
REMOTE_REF = "refs/remotes/origin/bot-state"
STATE_FILE = "hackathons.sqlite3"
NEW_BRANCH = "new"


class StateError(RuntimeError):
    """Indicate that durable reminder state could not be safely transferred."""


def _git(repo: Path, *args: str, data: bytes | None = None, allowed=(0,)) -> subprocess.CompletedProcess:
    """Run Git without a shell, hiding remote URLs from error messages."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True, timeout=30,
    )
    if result.returncode not in allowed:
        raise StateError(f"git {args[0]} failed (exit {result.returncode}); check access and remote state")
    return result


def _revision_path(database: Path) -> Path:
    """Keep the restored revision beside the runner's database."""
    return database.with_name(database.name + ".state-revision")


def _check_database(path: Path) -> None:
    """Reject corrupt databases and files without reminder state."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise StateError("SQLite integrity check failed")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(hackathons)")}
        if not {"id", "deadline", "reminded_7d", "reminded_1d"} <= columns:
            raise StateError("Database does not contain hackathon reminder state")


def restore(repo: Path, database: Path) -> None:
    """Restore a known revision; only a missing branch starts fresh state."""
    for suffix in ("", "-wal", "-shm", "-journal", ".state-revision"):
        if Path(str(database) + suffix).exists():
            raise StateError("Restore needs a fresh destination; existing local state was left untouched")
    database.parent.mkdir(parents=True, exist_ok=True)
    remote = _git(repo, "ls-remote", "--exit-code", "--heads", "origin", STATE_REF, allowed=(0, 2))
    if remote.returncode == 2:
        _revision_path(database).write_text(NEW_BRANCH + "\n", encoding="ascii")
        return
    _git(repo, "fetch", "--no-tags", "--depth=1", "origin", f"{STATE_REF}:{REMOTE_REF}")
    revision = _git(repo, "rev-parse", REMOTE_REF).stdout.decode("ascii").strip()
    content = _git(repo, "show", f"{revision}:{STATE_FILE}").stdout
    with TemporaryDirectory(dir=database.parent) as temp:
        candidate = Path(temp) / STATE_FILE
        candidate.write_bytes(content)
        _check_database(candidate)
        candidate.replace(database)
    _revision_path(database).write_text(revision + "\n", encoding="ascii")


def save(repo: Path, database: Path) -> bool:
    """Push a consistent snapshot without checking out files or forcing history."""
    revision = _revision_path(database).read_text(encoding="ascii").strip()
    if revision != NEW_BRANCH and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision) is None:
        raise StateError("Invalid restored revision; refusing to publish state")
    _check_database(database)
    with TemporaryDirectory() as temp:
        snapshot = Path(temp) / STATE_FILE
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
        blob = _git(repo, "hash-object", "-w", "--stdin", data=snapshot.read_bytes()).stdout.decode("ascii").strip()
    if revision != NEW_BRANCH:
        previous_blob = _git(repo, "rev-parse", f"{revision}:{STATE_FILE}").stdout.decode("ascii").strip()
        if blob == previous_blob:
            return False
    tree = _git(repo, "mktree", data=f"100644 blob {blob}\t{STATE_FILE}\n".encode("ascii")).stdout.decode("ascii").strip()
    parents = [] if revision == NEW_BRANCH else ["-p", revision]
    commit = _git(
        repo, "-c", "user.name=github-actions[bot]", "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit-tree", tree, *parents, data=b"Update reminder state\n",
    ).stdout.decode("ascii").strip()
    _git(repo, "push", "origin", f"{commit}:{STATE_REF}")
    _revision_path(database).write_text(commit + "\n", encoding="ascii")
    return True


def main() -> int:
    """Transfer state for a disposable runner, not a live local application."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "save"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=Path("data/hackathons.sqlite3"))
    args = parser.parse_args()
    try:
        if args.operation == "restore":
            restore(args.repo, args.database)
            print("Reminder state restored, or initialized for the first run")
        else:
            changed = save(args.repo, args.database)
            print("Reminder state saved" if changed else "Reminder state unchanged")
    except (StateError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        parser.exit(1, f"State transfer failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
