"""Load and validate the project's TOML configuration."""

from dataclasses import dataclass, field
from pathlib import Path
import math
import tomllib


@dataclass(frozen=True)
class HttpConfig:
    """Bound request volume and waiting time."""

    user_agent: str = "DevpostDeadlineReminder/0.1 (public listing; daily fetch)"
    connect_timeout: float = 10
    read_timeout: float = 30
    page_pause_seconds: float = 2
    per_page: int = 40
    max_pages: int = 10
    max_retries: int = 2
    max_retry_wait_seconds: float = 120


@dataclass(frozen=True)
class Config:
    """Keep server and local filter settings together."""

    online_only: bool = True
    statuses: tuple[str, ...] = ("open", "upcoming")
    themes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    http: HttpConfig = field(default_factory=HttpConfig)


def load_config(path: Path) -> Config:
    """Reject invalid values before making any requests."""
    with path.open("rb") as source:
        raw = tomllib.load(source)
    unknown = raw.keys() - {"online_only", "statuses", "themes", "keywords", "http"}
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    online = raw.get("online_only", True)
    if not isinstance(online, bool):
        raise ValueError("online_only must be a boolean")
    filters = {}
    for name, default in (("statuses", ["open", "upcoming"]), ("themes", []), ("keywords", [])):
        values = raw.get(name, default)
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f"{name} must be a list of nonempty strings")
        filters[name] = tuple(dict.fromkeys(v.strip() for v in values))
    if not filters["statuses"] or set(filters["statuses"]) - {"open", "upcoming"}:
        raise ValueError("statuses must contain open and/or upcoming")
    settings = raw.get("http", {})
    if not isinstance(settings, dict) or settings.keys() - HttpConfig.__dataclass_fields__.keys():
        raise ValueError("Invalid or unknown http configuration")
    http = HttpConfig(**settings)
    if not isinstance(http.user_agent, str) or not http.user_agent.strip() or any(c in http.user_agent for c in "\r\n"):
        raise ValueError("http.user_agent must be a nonempty single line")
    for name, minimum, maximum in (("per_page", 1, 40), ("max_pages", 1, 100), ("max_retries", 0, 3)):
        value = getattr(http, name)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"http.{name} must be an integer between {minimum} and {maximum}")
    for name in ("connect_timeout", "read_timeout", "page_pause_seconds", "max_retry_wait_seconds"):
        value = getattr(http, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"http.{name} must be a finite positive number")
    return Config(online_only=online, http=http, **filters)
