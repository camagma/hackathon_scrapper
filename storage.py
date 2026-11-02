"""Store normalized Devpost events and durable reminder flags in SQLite."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator

from dates import parse_submission_period
from fetch import plain_text


SCHEMA_VERSION = 1
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
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise ValueError(f"Unsupported database schema version: {version}")
        with connection:
            connection.execute(SCHEMA)
            connection.execute("CREATE INDEX IF NOT EXISTS hackathons_deadline ON hackathons(deadline, id)")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        yield connection


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
    events = []
    for row in connection.execute(query):
        values = dict(row)
        values["start_date"] = date.fromisoformat(values["start_date"])
        values["deadline"] = date.fromisoformat(values["deadline"])
        values["themes"] = tuple(json.loads(values["themes"]))
        for key in ("is_current", "reminded_7d", "reminded_1d"):
            values[key] = bool(values[key])
        events.append(Hackathon(**values))
    return events
