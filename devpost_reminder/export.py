"""Build filtered CSV exports in temporary directories using the standard library."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import Config, ExportConfig
from .filters import matches_fields
from .storage import Hackathon


COLUMNS = ("id", "title", "url", "start_date", "deadline", "days_left", "themes", "prize", "open_state")


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


@contextmanager
def generate_csv(events: Iterable[Hackathon], config: Config, today: date) -> Iterator[CsvExport | None]:
    """Yield a sorted CSV for current matching events, or None when empty."""
    unique = {event.id: event for event in events}
    selected = sorted(
        (event for event in unique.values() if event.is_current and matches_fields(
            config, title=event.title, themes=event.themes, organization_name=event.organization_name,
            location=event.location, open_state=event.open_state,
        )),
        key=lambda event: (event.deadline, event.id),
    )
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
