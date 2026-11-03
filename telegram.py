"""Read Telegram delivery credentials from the process environment."""

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class TelegramCredentials:
    """Keep credentials out of automatically generated representations."""

    token: str = field(repr=False)
    chat_id: str = field(repr=False)


def _required_environment(name: str) -> str:
    """Validate a required variable without including its value in errors."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set the {name} environment variable before Telegram delivery")
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} must not contain internal whitespace")
    return value


def load_telegram_credentials() -> TelegramCredentials:
    """Load credentials only when delivery is explicitly requested."""
    return TelegramCredentials(
        token=_required_environment("TELEGRAM_BOT_TOKEN"),
        chat_id=_required_environment("TELEGRAM_CHAT_ID"),
    )
