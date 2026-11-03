"""Coordinate fetching, storage, and reminders independently of the CLI."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import requests

from .config import Config
from .export import ExportDeliveryResult, deliver_export
from .fetch import fetch_hackathons, load_snapshot, matches
from .reminders import DeliveryResult, Reminder, current_date, deliver_reminders, pending_reminders
from .storage import Hackathon, SyncResult, list_hackathons, normalize, open_database, upsert_hackathons
from .telegram import TelegramClient, load_telegram_credentials


@dataclass(frozen=True)
class RunResult:
    """Return data for presentation without printing or choosing an exit code."""

    database_path: Path
    sync: SyncResult
    fetched_count: int
    events: tuple[Hackathon, ...]
    timezone: str
    preview_day: date | None = None
    preview: tuple[Reminder, ...] = ()
    delivery: DeliveryResult | None = None
    export_delivery: ExportDeliveryResult | None = None


def run(
    config: Config, *, mode: Literal["list", "preview", "send"] = "list",
    offline: Path | None = None, database_path: Path | None = None,
    today: date | None = None,
    send_export: bool = False,
) -> RunResult:
    """Sync events and optionally deliver reminders, CSV, or both."""
    if mode not in ("list", "preview", "send"):
        raise ValueError("Mode must be list, preview, or send")
    if today is not None and mode != "preview":
        raise ValueError("A date override requires preview mode")
    if send_export and mode == "preview":
        raise ValueError("CSV delivery cannot be combined with preview mode")
    sending = mode == "send" or send_export
    if sending and offline is not None:
        raise ValueError("Telegram delivery requires a live fetch")
    credentials = load_telegram_credentials() if sending else None
    items = load_snapshot(offline) if offline is not None else fetch_hackathons(config)
    selected_ids = {item["id"] for item in items if matches(item, config)}
    # Normalize the full batch before opening or changing persistent state.
    events = [normalize(item) for item in items]
    path = database_path.expanduser() if database_path is not None else config.database_path
    preview_day = None
    preview = ()
    delivery = None
    export_delivery = None
    with open_database(path) as connection:
        sync = upsert_hackathons(connection, events, complete_snapshot=offline is None)
        if mode == "preview":
            preview_day = today if today is not None else current_date(config)
            preview = tuple(pending_reminders(list_hackathons(connection, current_only=True), config, preview_day))
        if sending:
            day = current_date(config)
            with requests.Session() as session:
                client = TelegramClient(
                    credentials, session,
                    timeout=(config.http.connect_timeout, config.http.read_timeout),
                )
                if mode == "send":
                    delivery = deliver_reminders(connection, config, client.send_message, today=day)
                if send_export:
                    export_delivery = deliver_export(
                        connection, config, client.send_document, client.send_message, today=day,
                    )
    selected = tuple(sorted(
        (event for event in events if event.id in selected_ids),
        key=lambda event: (event.deadline, event.id),
    ))
    return RunResult(
        database_path=path, sync=sync, fetched_count=len(items), events=selected,
        timezone=config.timezone, preview_day=preview_day, preview=preview, delivery=delivery,
        export_delivery=export_delivery,
    )
