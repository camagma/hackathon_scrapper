"""Apply the same filters to fetched and stored hackathon metadata."""

from collections.abc import Iterable

from .config import Config


def matches_fields(
    config: Config, *, title: str, themes: Iterable[str], organization_name: str,
    location: str, open_state: str,
) -> bool:
    """Combine filters with AND and values within a filter with OR."""
    if open_state not in config.statuses:
        return False
    if config.online_only and location.casefold() != "online":
        return False
    names = [theme.casefold() for theme in themes]
    if config.themes and not any(theme.casefold() in names for theme in config.themes):
        return False
    text = " ".join([title, organization_name, *names]).casefold()
    return not config.keywords or any(keyword.casefold() in text for keyword in config.keywords)
