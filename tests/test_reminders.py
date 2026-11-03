"""Test exact calendar thresholds and filtering using fake events."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from devpost_reminder.config import Config
from devpost_reminder.reminders import current_date, days_until, due_reminder, format_reminder, pending_reminders
from devpost_reminder.storage import Hackathon


TODAY = date(2026, 11, 3)


@pytest.fixture
def event():
    return Hackathon(
        id=1, title="AI Agent Challenge", url="https://example.com/",
        start_date=date(2026, 11, 1), deadline=TODAY + timedelta(days=7),
        submission_period="Nov 01 - 10, 2026", themes=("Machine Learning/AI",),
        prize="$100", open_state="open", location="Online", organization_name="Example",
    )


@pytest.mark.parametrize("days", [-1, 0, 1, 2, 6, 7, 8, 14])
def test_exact_thresholds(event, days):
    event = replace(event, deadline=TODAY + timedelta(days=days))
    assert days_until(event.deadline, TODAY) == days
    reminder = due_reminder(event, Config(), TODAY)
    assert (reminder is not None) == (days in (1, 7))


@pytest.mark.parametrize("days,flag", [(7, "reminded_7d"), (1, "reminded_1d")])
def test_each_flag_suppresses_only_its_own_reminder(event, days, flag):
    event = replace(event, deadline=TODAY + timedelta(days=days), **{flag: True})
    assert due_reminder(event, Config(), TODAY) is None
    other_flag = "reminded_1d" if days == 7 else "reminded_7d"
    event = replace(event, **{flag: False, other_flag: True})
    assert due_reminder(event, Config(), TODAY).days_left == days


@pytest.mark.parametrize("changes", [
    {"is_current": False}, {"open_state": "closed"}, {"location": "London"},
    {"themes": ("AR/VR",)}, {"title": "Different event"},
])
def test_reapply_all_filters_to_stored_events(event, changes):
    config = Config(themes=("machine learning/ai",), keywords=("agent",))
    assert due_reminder(replace(event, **changes), config, TODAY) is None


def test_upcoming_event_is_eligible_when_configured(event):
    event = replace(event, open_state="upcoming")
    assert due_reminder(event, Config(), TODAY) is not None
    assert due_reminder(event, Config(statuses=("open",)), TODAY) is None


def test_selection_is_deduplicated_and_sorted(event):
    tomorrow = replace(event, id=2, deadline=TODAY + timedelta(days=1))
    selected = pending_reminders([event, tomorrow, event], Config(), TODAY)
    assert [reminder.event.id for reminder in selected] == [2, 1]


def test_message_contains_submission_deadline_days_and_link(event):
    reminder = due_reminder(event, Config(), TODAY)
    text = format_reminder(reminder)
    assert event.title in text
    assert "Дата окончания приёма проектов: 2026-11-10" in text
    assert "Осталось дней: 7" in text
    assert event.url in text
    assert "регистрац" not in text.casefold()


def test_midnight_uses_configured_timezone():
    now = datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc)
    assert current_date(Config(timezone="Etc/GMT-2"), now) == date(2026, 11, 4)
    assert current_date(Config(timezone="UTC"), now) == date(2026, 11, 3)


def test_offset_timezone_uses_calendar_dates():
    before = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    after = before + timedelta(hours=2)
    config = Config(timezone="Etc/GMT-2")
    assert current_date(config, before) == current_date(config, after) == date(2026, 10, 25)
    assert days_until(date(2026, 11, 1), current_date(config, after)) == 7


def test_clock_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone"):
        current_date(Config(), datetime(2026, 11, 3))
