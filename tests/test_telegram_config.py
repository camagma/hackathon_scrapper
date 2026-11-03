"""Check environment-only credentials without contacting Telegram."""

import pytest

from devpost_reminder.telegram import load_telegram_credentials


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Isolate tests from any credentials in the developer's environment."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")


def test_loads_credentials_from_environment():
    credentials = load_telegram_credentials()
    assert credentials.token == "fake-test-token"
    assert credentials.chat_id == "-1001234567890"


def test_credentials_do_not_appear_in_repr_or_str():
    credentials = load_telegram_credentials()
    for text in (repr(credentials), str(credentials)):
        assert credentials.token not in text
        assert credentials.chat_id not in text


@pytest.mark.parametrize("name", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_empty_values_fail_with_variable_name(monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_telegram_credentials()


@pytest.mark.parametrize("name", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_internal_whitespace_is_rejected_without_exposing_value(monkeypatch, name):
    value = "private value"
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name) as error:
        load_telegram_credentials()
    assert value not in str(error.value)


def test_surrounding_whitespace_is_trimmed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "  fake-test-token\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 12345 ")
    credentials = load_telegram_credentials()
    assert credentials.token == "fake-test-token"
    assert credentials.chat_id == "12345"
