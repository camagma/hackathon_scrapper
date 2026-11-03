"""Load Telegram credentials and send messages or CSVs through the HTTP Bot API."""

from dataclasses import dataclass, field
import os
import math
import time
from pathlib import Path

import requests


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


class TelegramError(RuntimeError):
    """Report delivery failure without credential-bearing URLs or raw bodies."""

    def __init__(self, message: str, *, status_code: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class TelegramClient:
    """Send with a caller-owned session, bounded timeouts, and no retries."""

    def __init__(
        self, credentials: TelegramCredentials, session: requests.Session,
        *, timeout: tuple[float, float] = (10, 30),
    ) -> None:
        if len(timeout) != 2 or any(not math.isfinite(value) or value <= 0 for value in timeout):
            raise ValueError("Telegram connect/read timeouts must be finite positive numbers")
        self._credentials = credentials
        self._session = session
        self._timeout = timeout
        self._blocked_until = 0.0

    def send_message(self, text: str) -> None:
        """Return only for a confirmed sendMessage result; raise on failure."""
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("Telegram text must contain 1–4096 characters and not be blank")
        self._send("sendMessage", json={"chat_id": self._credentials.chat_id, "text": text})

    def send_document(self, path: Path, caption: str = "") -> None:
        """Upload one CSV as multipart data and always close the input file."""
        if not isinstance(caption, str) or len(caption) > 1024:
            raise ValueError("Telegram caption must contain at most 1024 characters")
        with path.open("rb") as document:
            if os.fstat(document.fileno()).st_size == 0:
                raise ValueError("Telegram document must not be empty")
            self._send(
                "sendDocument", data={"chat_id": self._credentials.chat_id, "caption": caption},
                files={"document": (path.name, document, "text/csv")},
            )

    def _send(self, method: str, **payload) -> None:
        """Share response validation, cooldowns, and sanitized transport errors."""
        remaining = self._blocked_until - time.monotonic()
        if remaining > 0:
            raise TelegramError("Telegram rate limit cooldown is active", status_code=429,
                                retry_after=math.ceil(remaining))
        url = f"https://api.telegram.org/bot{self._credentials.token}/{method}"
        try:
            with self._session.post(
                url, timeout=self._timeout, allow_redirects=False, **payload,
            ) as response:
                status = response.status_code
                try:
                    body = response.json()
                except ValueError:
                    body = None
        except requests.RequestException:
            raise TelegramError("Telegram transport failed; delivery may be uncertain") from None
        code = body.get("error_code") if isinstance(body, dict) else None
        if status == 429 or code == 429:
            parameters = body.get("parameters") if isinstance(body, dict) else None
            delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
            delay = delay if type(delay) is int and delay > 0 else 60
            self._blocked_until = time.monotonic() + delay
            raise TelegramError("Telegram rate limit reached", status_code=429, retry_after=delay)
        if not 200 <= status < 300:
            raise TelegramError(f"Telegram HTTP error {status}", status_code=status)
        if not isinstance(body, dict) or body.get("ok") is not True:
            safe_code = code if type(code) is int else None
            raise TelegramError("Telegram did not confirm delivery", status_code=safe_code)
        result = body.get("result")
        if not isinstance(result, dict) or type(result.get("message_id")) is not int:
            raise TelegramError("Telegram returned an invalid message result")
