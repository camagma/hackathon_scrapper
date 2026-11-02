"""Select calendar-day reminders and format submission-deadline messages."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from config import Config
from filters import matches_fields
from storage import Hackathon


@dataclass(frozen=True)
class Reminder:
    """Describe one unsent 7-day or 1-day reminder."""

    event: Hackathon
    days_left: int


def current_date(config: Config, now: datetime | None = None) -> date:
    """Determine today's calendar date in the configured timezone."""
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Reminder clock must include a timezone")
    return instant.astimezone(ZoneInfo(config.timezone)).date()


def days_until(deadline: date, today: date) -> int:
    """Count calendar days without interpreting a deadline as a timestamp."""
    return (deadline - today).days


def due_reminder(event: Hackathon, config: Config, today: date) -> Reminder | None:
    """Select only current, matching events on an exact unsent threshold."""
    if not event.is_current or not matches_fields(
        config, title=event.title, themes=event.themes,
        organization_name=event.organization_name, location=event.location,
        open_state=event.open_state,
    ):
        return None
    days = days_until(event.deadline, today)
    if (days == 7 and not event.reminded_7d) or (days == 1 and not event.reminded_1d):
        return Reminder(event, days)
    return None


def pending_reminders(events: Iterable[Hackathon], config: Config, today: date) -> list[Reminder]:
    """Return each eligible event once, in deadline and ID order."""
    unique = {event.id: event for event in events}
    ordered = sorted(unique.values(), key=lambda event: (event.deadline, event.id))
    return [reminder for event in ordered if (reminder := due_reminder(event, config, today)) is not None]


def format_reminder(reminder: Reminder) -> str:
    """Name the submission deadline explicitly, without a registration claim."""
    return (
        f"{reminder.event.title}\n"
        f"Дата окончания приёма проектов: {reminder.event.deadline.isoformat()}\n"
        f"Осталось дней: {reminder.days_left}\n"
        f"{reminder.event.url}"
    )
