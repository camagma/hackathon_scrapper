"""Fetch, store, and list Devpost hackathons matching configured filters."""

import argparse
from datetime import date
import logging
from pathlib import Path
import sqlite3
import sys

import requests

from config import load_config
from fetch import FetchError, fetch_hackathons, load_snapshot, matches
from reminders import current_date, deliver_reminders, format_reminder, pending_reminders
from storage import list_hackathons, normalize, open_database, upsert_hackathons
from telegram import TelegramClient, load_telegram_credentials


def main() -> int:
    """Print matching events, or exit nonzero on incomplete retrieval."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    parser.add_argument("--offline", type=Path, help="Read a saved page without network access")
    parser.add_argument("--db", type=Path, help="Override database path (relative to current directory)")
    delivery = parser.add_mutually_exclusive_group()
    delivery.add_argument("--preview-reminders", action="store_true", help="Print pending reminders without sending or marking them")
    delivery.add_argument("--send-reminders", action="store_true", help="Send due reminders to Telegram after a complete live fetch")
    parser.add_argument("--today", type=date.fromisoformat, help="Preview date override (YYYY-MM-DD)")
    args = parser.parse_args()
    if args.today is not None and not args.preview_reminders:
        parser.error("--today requires --preview-reminders")
    if args.send_reminders and args.offline is not None:
        parser.error("--send-reminders requires a live fetch; use --preview-reminders for snapshots")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = load_config(args.config)
        credentials = load_telegram_credentials() if args.send_reminders else None
        items = load_snapshot(args.offline) if args.offline else fetch_hackathons(config)
        selected_ids = {item["id"] for item in items if matches(item, config)}
        # Parse the entire batch before opening or changing persistent state.
        events = [normalize(item) for item in items]
        database_path = args.db.expanduser() if args.db is not None else config.database_path
        with open_database(database_path) as connection:
            result = upsert_hackathons(connection, events, complete_snapshot=args.offline is None)
            if args.preview_reminders:
                day = args.today if args.today is not None else current_date(config)
                preview = pending_reminders(list_hackathons(connection, current_only=True), config, day)
            if args.send_reminders:
                with requests.Session() as session:
                    client = TelegramClient(
                        credentials, session,
                        timeout=(config.http.connect_timeout, config.http.read_timeout),
                    )
                    delivered = deliver_reminders(connection, config, client.send_message)
        selected = sorted(
            (event for event in events if event.id in selected_ids),
            key=lambda event: (event.deadline, event.id),
        )
    except (OSError, ValueError, FetchError, requests.RequestException, sqlite3.Error) as exc:
        logging.error("Unable to sync hackathons: %s", exc)
        return 1
    print(f"SQLite: {result.inserted} new, {result.refreshed} refreshed | {database_path}")
    print(f"Matching hackathons: {len(selected)} / {len(items)} fetched")
    for event in selected:
        print(f"\n[{event.id}] {event.title}")
        print(f"  State: {event.open_state} | Location: {event.location}")
        print(f"  Submission start: {event.start_date} | Submission deadline: {event.deadline}")
        print(f"  Submission period: {event.submission_period}")
        print(f"  Themes: {', '.join(event.themes) or '-'}")
        print(f"  Prize: {event.prize or '-'}")
        print(f"  {event.url}")
    if args.preview_reminders:
        print(f"\nReminder preview for {day} ({config.timezone}): {len(preview)} pending")
        for reminder in preview:
            print(f"\n{format_reminder(reminder)}")
    if args.send_reminders:
        print(f"\nTelegram reminders: {delivered.sent} sent, {delivered.failed} failed, {delivered.skipped} skipped")
        return 1 if delivered.failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
