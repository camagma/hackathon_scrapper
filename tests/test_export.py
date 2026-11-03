"""Check CSV contents, selection, ordering, encoding, and temporary-file cleanup."""

import codecs
import csv
from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from devpost_reminder.config import Config
from devpost_reminder.export import COLUMNS, generate_csv
from devpost_reminder.storage import Hackathon, list_hackathons, open_database, upsert_hackathons


TODAY = date(2026, 11, 3)


@pytest.fixture
def event():
    return Hackathon(
        id=1, title='AI, "агенти"\nChallenge', url="https://example.com/",
        start_date=date(2026, 11, 1), deadline=date(2026, 11, 10),
        submission_period="Nov 01 - 10, 2026", themes=("Machine Learning/AI", "Наука"),
        prize="$67,500", open_state="open", location="Online", organization_name="Example",
    )


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        assert reader.fieldnames == list(COLUMNS)
        return list(reader)


def test_csv_preserves_all_fields_unicode_and_csv_quoting(event):
    with generate_csv([event], Config(), TODAY) as report:
        assert report.path.read_bytes().startswith(codecs.BOM_UTF8)
        assert read_rows(report.path) == [{
            "id": "1", "title": event.title, "url": event.url,
            "start_date": "2026-11-01", "deadline": "2026-11-10", "days_left": "7",
            "themes": "Machine Learning/AI; Наука", "prize": "$67,500", "open_state": "open",
        }]
        assert report.count == 1
        assert report.nearest_deadline == event.deadline


def test_sorting_uses_deadline_then_id_and_deduplicates(event):
    events = [replace(event, id=3), replace(event, id=2, deadline=date(2026, 11, 4)), event, event]
    with generate_csv(events, Config(), TODAY) as report:
        assert [row["id"] for row in read_rows(report.path)] == ["2", "1", "3"]
        assert report.event_ids == (2, 1, 3)
        assert report.count == 3
        assert report.nearest_deadline == date(2026, 11, 4)


@pytest.mark.parametrize("change", [
    {"is_current": False}, {"open_state": "closed"}, {"location": "London"},
    {"themes": ("AR/VR",)}, {"organization_name": "Other"},
])
def test_all_filters_apply_to_export(event, change):
    config = Config(themes=("machine learning/ai",), keywords=("example",))
    with generate_csv([event, replace(event, id=2, **change)], config, TODAY) as report:
        assert report.event_ids == (1,)


def test_upcoming_and_in_person_settings_are_respected(event):
    upcoming = replace(event, open_state="upcoming", location="London")
    with generate_csv([upcoming], Config(online_only=False), TODAY) as report:
        assert report.count == 1
        assert read_rows(report.path)[0]["open_state"] == "upcoming"


@pytest.mark.parametrize("days,deadline", [(0, date(2026, 11, 3)), (-1, date(2026, 11, 2))])
def test_days_left_is_a_calendar_difference_without_an_extra_date_filter(event, days, deadline):
    with generate_csv([replace(event, deadline=deadline)], Config(), TODAY) as report:
        assert read_rows(report.path)[0]["days_left"] == str(days)


def test_empty_selection_creates_no_temporary_directory(event, monkeypatch):
    temporary = Mock(side_effect=AssertionError("No file should be created"))
    monkeypatch.setattr("devpost_reminder.export.TemporaryDirectory", temporary)
    for events in ([], [replace(event, is_current=False)]):
        with generate_csv(events, Config(), TODAY) as report:
            assert report is None
    temporary.assert_not_called()


def test_temporary_file_is_removed_on_success_and_failure(event):
    with generate_csv([event], Config(), TODAY) as report:
        path = report.path
        assert path.exists()
    assert not path.parent.exists()
    with pytest.raises(RuntimeError, match="Upload failed"):
        with generate_csv([event], Config(), TODAY) as report:
            failed_path = report.path
            raise RuntimeError("Upload failed")
    assert not failed_path.parent.exists()


def test_export_uses_stored_data_without_changing_reminder_state(event, tmp_path):
    with open_database(tmp_path / "state.sqlite3") as connection:
        upsert_hackathons(connection, [event])
        with connection:
            connection.execute("UPDATE hackathons SET reminded_7d = 1 WHERE id = 1")
        before = list_hackathons(connection)
        with generate_csv(before, Config(), TODAY) as report:
            assert report.count == 1
        assert list_hackathons(connection) == before
