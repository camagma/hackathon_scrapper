"""Fetch bounded Devpost listing pages and apply local filters."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import logging
from pathlib import Path
import json
import time
from urllib.robotparser import RobotFileParser

import requests

from config import Config


ENDPOINT = "https://devpost.com/api/hackathons"
ROBOTS_URL = "https://devpost.com/robots.txt"
LOG = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Indicate a failed or incomplete listing fetch."""


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    """Remove HTML and decode entities in display fields."""
    parser = _TextParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def validate_page(data: object) -> tuple[list[dict], dict]:
    """Fail explicitly when the unofficial response schema changes."""
    if not isinstance(data, dict) or not isinstance(data.get("hackathons"), list):
        raise FetchError("Expected a JSON object with a hackathons array")
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise FetchError("Missing listing metadata")
    for key in ("total_count", "per_page"):
        value = meta.get(key)
        if type(value) is not int or value < (1 if key == "per_page" else 0):
            raise FetchError(f"Invalid meta.{key}")
    for item in data["hackathons"]:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise FetchError("Invalid hackathon ID")
        for key in ("title", "url", "open_state", "submission_period_dates", "prize_amount"):
            if not isinstance(item.get(key), str):
                raise FetchError(f"Hackathon {item['id']}: invalid {key}")
        location = item.get("displayed_location")
        if not isinstance(location, dict) or not isinstance(location.get("location"), str):
            raise FetchError(f"Hackathon {item['id']}: invalid displayed_location")
        themes = item.get("themes")
        if not isinstance(themes, list) or any(not isinstance(t, dict) or not isinstance(t.get("name"), str) for t in themes):
            raise FetchError(f"Hackathon {item['id']}: invalid themes")
    return data["hackathons"], meta


def matches(item: dict, config: Config) -> bool:
    """Combine filters with AND, and values inside each filter with OR."""
    if item["open_state"] not in config.statuses:
        return False
    if config.online_only and item["displayed_location"]["location"].casefold() != "online":
        return False
    themes = [plain_text(t["name"]).casefold() for t in item["themes"]]
    if config.themes and not any(t.casefold() in themes for t in config.themes):
        return False
    text = " ".join([plain_text(item["title"]), plain_text(item.get("organization_name") or ""), *themes]).casefold()
    return not config.keywords or any(k.casefold() in text for k in config.keywords)


class DevpostClient:
    """Use one session with explicit limits and no hidden adapter retries."""

    def __init__(self, config: Config, session: requests.Session) -> None:
        self.config = config
        self.session = session
        self.pause = config.http.page_pause_seconds
        self.last_request: float | None = None

    def _get(self, url: str, params=None) -> requests.Response:
        settings = self.config.http
        for attempt in range(settings.max_retries + 1):
            if self.last_request is not None:
                time.sleep(max(0, self.pause - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = self.session.get(
                url, params=params, timeout=(settings.connect_timeout, settings.read_timeout),
                headers={"User-Agent": settings.user_agent},
            )
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response
            if attempt == settings.max_retries:
                response.raise_for_status()
            delay = max(self.pause, 2 ** (attempt + 1))
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    try:
                        until = parsedate_to_datetime(retry_after)
                        if until.tzinfo is None:
                            until = until.replace(tzinfo=timezone.utc)
                        delay = max(delay, (until - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        raise FetchError("Invalid Retry-After; stopping to avoid excessive requests")
            if not delay <= settings.max_retry_wait_seconds:
                raise FetchError("Retry-After exceeds configured wait limit; try a later run")
            LOG.warning("Devpost returned HTTP %s; retrying in %.1fs", response.status_code, delay)
            response.close()
            time.sleep(delay)
        raise FetchError("Request retry limit reached")

    def fetch(self) -> list[dict]:
        """Check robots.txt and collect all pages, rejecting partial results."""
        with self._get(ROBOTS_URL) as response:
            policy = RobotFileParser()
            policy.parse(response.text.splitlines())
        if not policy.can_fetch(self.config.http.user_agent, ENDPOINT):
            raise FetchError("robots.txt disallows the listing endpoint")
        self.pause = max(self.pause, policy.crawl_delay(self.config.http.user_agent) or 0)
        rate = policy.request_rate(self.config.http.user_agent)
        if rate:
            self.pause = max(self.pause, rate.seconds / rate.requests)
        params = [("per_page", self.config.http.per_page)]
        params.extend(("status[]", state) for state in self.config.statuses)
        if self.config.online_only:
            params.append(("challenge_type[]", "online"))
        records: dict[int, dict] = {}
        for page in range(1, self.config.http.max_pages + 1):
            with self._get(ENDPOINT, params=[*params, ("page", page)]) as response:
                items, meta = validate_page(response.json())
            LOG.info("Page %d: %d records (total reported: %d)", page, len(items), meta["total_count"])
            if not items and len(records) < meta["total_count"]:
                raise FetchError("Unexpected empty page before the reported end")
            previous = len(records)
            records.update((item["id"], item) for item in items)
            if len(records) >= meta["total_count"]:
                return list(records.values())
            if len(records) == previous:
                raise FetchError("Pagination made no progress; refusing incomplete results")
        raise FetchError("Page limit reached; increase http.max_pages to fetch the complete listing")


def load_snapshot(path: Path) -> list[dict]:
    """Read a single saved page for offline exploration."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items, meta = validate_page(data)
    if len(items) < meta["total_count"]:
        LOG.warning("Offline snapshot contains %d of %d reported records", len(items), meta["total_count"])
    return list({item["id"]: item for item in items}.values())


def fetch_hackathons(config: Config) -> list[dict]:
    """Close the session after fetching the public listing."""
    with requests.Session() as session:
        return DevpostClient(config, session).fetch()
