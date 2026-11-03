"""Store normalized Devpost events and durable reminder flags in SQLite."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator

from .dates import parse_submission_period
from .fetch import plain_text


SCHEMA_VERSION = 3
SCHEMA = """
CREATE TABLE IF NOT EXISTS hackathons (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    start_date TEXT NOT NULL,
    deadline TEXT NOT NULL,
    submission_period TEXT NOT NULL,
    themes TEXT NOT NULL,
    prize TEXT NOT NULL,
    open_state TEXT NOT NULL,
    location TEXT NOT NULL,
    organization_name TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    reminded_7d INTEGER NOT NULL DEFAULT 0 CHECK (reminded_7d IN (0, 1)),
    reminded_1d INTEGER NOT NULL DEFAULT 0 CHECK (reminded_1d IN (0, 1)),
    CHECK (length(start_date) = 10 AND length(deadline) = 10),
    CHECK (start_date <= deadline)
)
"""

EXPORT_SCHEMA = """
CREATE TABLE export_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_success TEXT NOT NULL CHECK (length(last_success) = 10),
    event_ids TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class Hackathon:
    """Represent a stored event with calendar dates and plain display text."""

    id: int
    title: str
    url: str
    start_date: date
    deadline: date
    submission_period: str
    themes: tuple[str, ...]
    prize: str
    open_state: str
    location: str
    organization_name: str
    is_current: bool = True
    reminded_7d: bool = False
    reminded_1d: bool = False
    reminded_start_7d: bool = False
    reminded_start_1d: bool = False


def normalize(item: dict) -> Hackathon:
    """Normalize a validated listing item without deriving time information."""
    try:
        start, deadline = parse_submission_period(item["submission_period_dates"])
    except ValueError as exc:
        raise ValueError(f"Hackathon {item['id']}: {exc}") from exc
    return Hackathon(
        id=item["id"], title=plain_text(item["title"]), url=item["url"],
        start_date=start, deadline=deadline,
        submission_period=item["submission_period_dates"],
        themes=tuple(plain_text(t["name"]) for t in item["themes"]),
        prize=plain_text(item["prize_amount"]), open_state=item["open_state"],
        location=plain_text(item["displayed_location"]["location"]),
        organization_name=plain_text(item.get("organization_name") or ""),
    )


@contextmanager
def open_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Initialize a versioned database and always close its connection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, SCHEMA_VERSION):
                raise ValueError(f"Unsupported database schema version: {version}")
            connection.execute(SCHEMA)
            connection.execute("CREATE INDEX IF NOT EXISTS hackathons_deadline ON hackathons(deadline, id)")
            if version < 2:
                connection.execute(EXPORT_SCHEMA)
            if version < 3:
                for column in ("reminded_start_7d", "reminded_start_1d"):
                    connection.execute(
                        f"ALTER TABLE hackathons ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0 CHECK ({column} IN (0, 1))"
                    )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        yield connection


@dataclass(frozen=True)
class ExportState:
    """Track the last confirmed export independently of reminder flags."""

    last_success: date | None = None
    event_ids: frozenset[int] = frozenset()

    def has_new(self, event_ids: Iterable[int]) -> bool:
        """Detect IDs absent from the most recent successful export."""
        return bool(set(event_ids) - self.event_ids)


def read_export_state(connection: sqlite3.Connection) -> ExportState:
    """Return empty state before the first success, without writing a row."""
    row = connection.execute("SELECT last_success, event_ids FROM export_state WHERE singleton = 1").fetchone()
    if row is None:
        return ExportState()
    ids = json.loads(row["event_ids"])
    if not isinstance(ids, list) or any(type(value) is not int for value in ids):
        raise ValueError("Invalid event IDs in stored export state")
    return ExportState(date.fromisoformat(row["last_success"]), frozenset(ids))


def record_export_success(
    connection: sqlite3.Connection, exported_on: date, event_ids: Iterable[int],
) -> None:
    """Record confirmed delivery in the caller's explicit transaction."""
    if not connection.in_transaction:
        raise RuntimeError("Export state requires an explicit transaction")
    ids = list(event_ids)
    if any(type(value) is not int for value in ids):
        raise ValueError("Export event IDs must be integers")
    previous = read_export_state(connection)
    if previous.last_success is not None and exported_on < previous.last_success:
        raise ValueError("Export success date cannot move backwards")
    connection.execute(
        """INSERT INTO export_state (singleton, last_success, event_ids) VALUES (1, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            last_success = excluded.last_success, event_ids = excluded.event_ids""",
        (exported_on.isoformat(), json.dumps(sorted(set(ids)))),
    )


@dataclass(frozen=True)
class SyncResult:
    """Summarize unique events inserted or refreshed by a sync."""

    inserted: int
    refreshed: int


UPSERT = """
INSERT INTO hackathons (
    id, title, url, start_date, deadline, submission_period, themes, prize,
    open_state, location, organization_name
) VALUES (
    :id, :title, :url, :start_date, :deadline, :submission_period, :themes, :prize,
    :open_state, :location, :organization_name
)
ON CONFLICT(id) DO UPDATE SET
    title = excluded.title,
    url = excluded.url,
    start_date = excluded.start_date,
    deadline = excluded.deadline,
    submission_period = excluded.submission_period,
    themes = excluded.themes,
    prize = excluded.prize,
    open_state = excluded.open_state,
    location = excluded.location,
    organization_name = excluded.organization_name,
    is_current = 1
"""


def upsert_hackathons(
    connection: sqlite3.Connection,
    events: Iterable[Hackathon],
    *,
    complete_snapshot: bool = False,
) -> SyncResult:
    """Atomically refresh events without resetting either reminder flag."""
    unique = {event.id: event for event in events}
    rows = [
        {
            "id": event.id, "title": event.title, "url": event.url,
            "start_date": event.start_date.isoformat(), "deadline": event.deadline.isoformat(),
            "submission_period": event.submission_period,
            "themes": json.dumps(event.themes, ensure_ascii=False), "prize": event.prize,
            "open_state": event.open_state, "location": event.location,
            "organization_name": event.organization_name,
        }
        for event in unique.values()
    ]
    with connection:
        # Serialize concurrent writers before counting or changing snapshot membership.
        connection.execute("BEGIN IMMEDIATE")
        existing = {row[0] for row in connection.execute("SELECT id FROM hackathons")}
        if complete_snapshot:
            connection.execute("UPDATE hackathons SET is_current = 0 WHERE is_current = 1")
        connection.executemany(UPSERT, rows)
    inserted = len(unique.keys() - existing)
    return SyncResult(inserted=inserted, refreshed=len(unique) - inserted)


def list_hackathons(
    connection: sqlite3.Connection, *, current_only: bool = False,
) -> list[Hackathon]:
    """Read events in deadline order, optionally excluding absent events."""
    query = "SELECT * FROM hackathons"
    if current_only:
        query += " WHERE is_current = 1"
    query += " ORDER BY deadline, id"
    return [_decode_event(row) for row in connection.execute(query)]


def _decode_event(row: sqlite3.Row) -> Hackathon:
    """Restore calendar dates, theme names, and boolean flags from one row."""
    values = dict(row)
    values["start_date"] = date.fromisoformat(values["start_date"])
    values["deadline"] = date.fromisoformat(values["deadline"])
    values["themes"] = tuple(json.loads(values["themes"]))
    for key in ("is_current", "reminded_7d", "reminded_1d", "reminded_start_7d", "reminded_start_1d"):
        values[key] = bool(values[key])
    return Hackathon(**values)


def get_hackathon(connection: sqlite3.Connection, event_id: int) -> Hackathon | None:
    """Reload an event before deciding whether to send its reminder."""
    row = connection.execute("SELECT * FROM hackathons WHERE id = ?", (event_id,)).fetchone()
    return _decode_event(row) if row is not None else None


def mark_reminded(
    connection: sqlite3.Connection, event_id: int, days: int, *, before_start: bool = False,
) -> bool:
    """Set one reminder flag inside the caller's transaction, without committing."""
    if type(days) is not int or days not in (7, 1):
        raise ValueError("Reminder threshold must be 7 or 1 days")
    if not connection.in_transaction:
        raise RuntimeError("Reminder flags require an explicit transaction")
    column = ({7: "reminded_start_7d", 1: "reminded_start_1d"} if before_start
              else {7: "reminded_7d", 1: "reminded_1d"})[days]
    result = connection.execute(
        f"UPDATE hackathons SET {column} = 1 WHERE id = ? AND {column} = 0",
        (event_id,),
    )
    return result.rowcount == 1
