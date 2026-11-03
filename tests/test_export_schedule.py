"""Test export configuration and calendar schedules without network access."""

from datetime import date

import pytest

from devpost_reminder.config import ExportConfig, load_config
from devpost_reminder.export import export_due


MONDAY = date(2026, 11, 2)
TUESDAY = date(2026, 11, 3)


def test_default_schedule_is_weekly_on_monday(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    assert load_config(config).export == ExportConfig(mode="weekly", weekday=0)


@pytest.mark.parametrize("mode", ["daily", "weekly", "new"])
def test_toml_loads_export_settings(tmp_path, mode):
    config = tmp_path / "config.toml"
    config.write_text(f'[export]\nmode = "{mode}"\nweekday = 6\n', encoding="utf-8")
    assert load_config(config).export == ExportConfig(mode=mode, weekday=6)


@pytest.mark.parametrize("content", [
    'export = "weekly"', '[export]\nmode = "monthly"', '[export]\nmode = 1',
    '[export]\nweekday = -1', '[export]\nweekday = 7', '[export]\nweekday = true',
    '[export]\nweekday = "Monday"', '[export]\nweekday = 1.0', '[export]\ntypo = 1',
])
def test_invalid_settings_fail_before_running(tmp_path, content):
    config = tmp_path / "config.toml"
    config.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="export"):
        load_config(config)


def test_daily_exports_once_per_calendar_date():
    settings = ExportConfig(mode="daily")
    assert export_due(settings, MONDAY, None)
    assert not export_due(settings, MONDAY, MONDAY)
    assert export_due(settings, TUESDAY, MONDAY)


def test_weekly_exports_only_on_configured_day():
    settings = ExportConfig()
    assert export_due(settings, MONDAY, None)
    assert not export_due(settings, TUESDAY, None)
    assert not export_due(settings, MONDAY, MONDAY)
    assert export_due(settings, date(2026, 11, 9), MONDAY)
    assert export_due(ExportConfig(weekday=1), TUESDAY, MONDAY)


def test_new_mode_requires_new_events_and_allows_same_day_changes():
    settings = ExportConfig(mode="new")
    assert not export_due(settings, MONDAY, None, has_new=False)
    assert export_due(settings, MONDAY, None, has_new=True)
    assert not export_due(settings, MONDAY, MONDAY, has_new=False)
    assert export_due(settings, MONDAY, MONDAY, has_new=True)


@pytest.mark.parametrize("mode", ["daily", "weekly", "new"])
def test_clock_rollback_does_not_send_before_last_success(mode):
    assert not export_due(ExportConfig(mode=mode), MONDAY, TUESDAY, has_new=True)


def test_daily_schedule_handles_year_boundary():
    assert export_due(ExportConfig(mode="daily"), date(2027, 1, 1), date(2026, 12, 31))


def test_direct_config_construction_is_validated():
    with pytest.raises(ValueError, match="export.mode"):
        ExportConfig(mode="invalid")
    with pytest.raises(ValueError, match="export.weekday"):
        ExportConfig(weekday=True)
