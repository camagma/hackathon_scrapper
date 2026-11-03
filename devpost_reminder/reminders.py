"""Remind users before upcoming hackathons open for submissions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
import sqlite3
from typing import Iterable
from zoneinfo import ZoneInfo

from .config import Config
from .filters import matches_fields
from .storage import Hackathon, get_hackathon, list_hackathons, mark_reminded


LOG = logging.getLogger(__name__)


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
    if event.open_state != "upcoming" or not event.is_current or not matches_fields(
        config, title=event.title, themes=event.themes,
        organization_name=event.organization_name, location=event.location,
        open_state=event.open_state,
    ):
        return None
    days = days_until(event.start_date, today)
    if (days == 7 and not event.reminded_start_7d) or (days == 1 and not event.reminded_start_1d):
        return Reminder(event, days)
    return None


def pending_reminders(events: Iterable[Hackathon], config: Config, today: date) -> list[Reminder]:
    """Return each eligible event once, in opening-date and ID order."""
    unique = {event.id: event for event in events}
    ordered = sorted(unique.values(), key=lambda event: (event.start_date, event.id))
    return [reminder for event in ordered if (reminder := due_reminder(event, config, today)) is not None]


def format_reminder(reminder: Reminder) -> str:
    """Identify the opening date without claiming a registration deadline."""
    return (
        f"{reminder.event.title}\n"
        f"Submissions open: {reminder.event.start_date.isoformat()}\n"
        f"Days until opening: {reminder.days_left}\n"
        f"Submission deadline: {reminder.event.deadline.isoformat()}\n"
        f"{reminder.event.url}"
    )


@dataclass(frozen=True)
class DeliveryResult:
    """Summarize confirmed sends, sender failures, and stale candidates."""

    sent: int = 0
    failed: int = 0
    skipped: int = 0


def deliver_reminders(
    connection: sqlite3.Connection, config: Config, send: Callable[[str], None],
    *, today: date | None = None,
) -> DeliveryResult:
    """Send through a callback that raises on failure, then commit each flag."""
    day = today if today is not None else current_date(config)
    candidates = pending_reminders(list_hackathons(connection, current_only=True), config, day)
    sent = failed = skipped = 0
    for candidate in candidates:
        with connection:
            # Hold the write lock across recheck, send, and flag update so another
            # process sharing this file cannot send the same reminder concurrently.
            connection.execute("BEGIN IMMEDIATE")
            event = get_hackathon(connection, candidate.event.id)
            reminder = due_reminder(event, config, day) if event is not None else None
            if reminder is None or reminder.days_left != candidate.days_left:
                skipped += 1
                continue
            try:
                send(format_reminder(reminder))
            except Exception as exc:
                # Transport exception strings can contain credential-bearing URLs.
                LOG.error("Reminder failed: id=%s days=%s error_type=%s",
                          event.id, reminder.days_left, type(exc).__name__)
                failed += 1
                continue
            if not mark_reminded(connection, event.id, reminder.days_left, before_start=True):
                raise RuntimeError("Reminder state changed unexpectedly during delivery")
        sent += 1
    return DeliveryResult(sent=sent, failed=failed, skipped=skipped)
