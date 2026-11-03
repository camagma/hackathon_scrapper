"""Build filtered CSV exports in temporary directories using the standard library."""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import date
import logging
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import Literal

from .config import Config, ExportConfig
from .filters import matches_fields
from .storage import Hackathon, list_hackathons, read_export_state, record_export_success


COLUMNS = ("id", "title", "url", "start_date", "deadline", "days_left", "themes", "prize", "open_state")
LOG = logging.getLogger(__name__)


def export_due(
    settings: ExportConfig, today: date, last_success: date | None, *, has_new: bool = False,
) -> bool:
    """Check a calendar schedule using the last confirmed successful export."""
    if last_success is not None and last_success > today:
        return False
    if settings.mode == "new":
        return has_new
    if last_success == today:
        return False
    return settings.mode == "daily" or today.weekday() == settings.weekday


@dataclass(frozen=True)
class CsvExport:
    """Describe a temporary export that remains available inside its context."""

    path: Path
    event_ids: tuple[int, ...]
    nearest_deadline: date

    @property
    def count(self) -> int:
        """Return the number of unique hackathons in the file."""
        return len(self.event_ids)

    @property
    def caption(self) -> str:
        """Summarize the file without claiming a registration deadline."""
        return (
            f"Hackathons in this file: {self.count}. "
            f"Nearest submission deadline: {self.nearest_deadline.isoformat()}."
        )


def select_export_events(events: Iterable[Hackathon], config: Config) -> list[Hackathon]:
    """Select the same unique, sorted records for scheduling and CSV contents."""
    unique = {event.id: event for event in events}
    return sorted(
        (event for event in unique.values() if event.is_current and matches_fields(
            config, title=event.title, themes=event.themes, organization_name=event.organization_name,
            location=event.location, open_state=event.open_state,
        )),
        key=lambda event: (event.deadline, event.id),
    )


@contextmanager
def generate_csv(events: Iterable[Hackathon], config: Config, today: date) -> Iterator[CsvExport | None]:
    """Yield a sorted CSV for current matching events, or None when empty."""
    selected = select_export_events(events, config)
    if not selected:
        yield None
        return
    with TemporaryDirectory(prefix="devpost-export-") as directory:
        path = Path(directory) / "hackathons.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=COLUMNS)
            writer.writeheader()
            for event in selected:
                writer.writerow({
                    "id": event.id, "title": event.title, "url": event.url,
                    "start_date": event.start_date.isoformat(), "deadline": event.deadline.isoformat(),
                    "days_left": (event.deadline - today).days, "themes": "; ".join(event.themes),
                    "prize": event.prize, "open_state": event.open_state,
                })
        yield CsvExport(path, tuple(event.id for event in selected), selected[0].deadline)


@dataclass(frozen=True)
class ExportDeliveryResult:
    """Report an export outcome independently of reminder delivery."""

    status: Literal["sent", "empty", "skipped", "failed"]
    count: int = 0


def deliver_export(
    connection: sqlite3.Connection, config: Config,
    send_document: Callable[[Path, str], None], send_message: Callable[[str], None],
    *, today: date,
) -> ExportDeliveryResult:
    """Deliver a due export and record success; contain failures for reminders."""
    try:
        with connection:
            # Serialize selection, delivery, and success recording for one database.
            connection.execute("BEGIN IMMEDIATE")
            events = select_export_events(list_hackathons(connection, current_only=True), config)
            ids = tuple(event.id for event in events)
            state = read_export_state(connection)
            if not export_due(config.export, today, state.last_success, has_new=state.has_new(ids)):
                return ExportDeliveryResult("skipped")
            with generate_csv(events, config, today) as report:
                if report is None:
                    send_message("No hackathons match your current filters.")
                else:
                    send_document(report.path, report.caption)
            record_export_success(connection, today, ids)
        return ExportDeliveryResult("sent" if ids else "empty", len(ids))
    except Exception as exc:
        # Transport exceptions can contain a credential-bearing URL.
        LOG.error("CSV export failed: error_type=%s", type(exc).__name__)
        return ExportDeliveryResult("failed")
