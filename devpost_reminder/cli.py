"""Fetch, store, and list Devpost hackathons matching configured filters."""

import argparse
from datetime import date
import logging
from pathlib import Path
import sqlite3
import sys

import requests

from .app import RunResult, run
from .config import load_config
from .fetch import FetchError
from .reminders import format_reminder


def parse_args() -> argparse.Namespace:
    """Parse CLI options and reject incompatible modes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / "config.toml")
    parser.add_argument("--offline", type=Path, help="Read a saved page without network access")
    parser.add_argument("--db", type=Path, help="Override database path (relative to current directory)")
    delivery = parser.add_mutually_exclusive_group()
    delivery.add_argument("--preview-reminders", action="store_true", help="Print pending reminders without sending or marking them")
    delivery.add_argument("--send-reminders", action="store_true", help="Send due reminders to Telegram after a complete live fetch")
    parser.add_argument("--send-export", action="store_true", help="Send a CSV or empty-result text when the export schedule is due")
    parser.add_argument("--today", type=date.fromisoformat, help="Preview date override (YYYY-MM-DD)")
    args = parser.parse_args()
    if args.today is not None and not args.preview_reminders:
        parser.error("--today requires --preview-reminders")
    if args.send_reminders and args.offline is not None:
        parser.error("--send-reminders requires a live fetch; use --preview-reminders for snapshots")
    if args.send_export and (args.offline is not None or args.preview_reminders):
        parser.error("--send-export requires a live fetch and cannot be combined with preview mode")
    return args


def print_result(result: RunResult) -> None:
    """Render a completed sync and any reminder results."""
    print(f"SQLite: {result.sync.inserted} new, {result.sync.refreshed} refreshed | {result.database_path}")
    print(f"Matching hackathons: {len(result.events)} / {result.fetched_count} fetched")
    for event in result.events:
        print(f"\n[{event.id}] {event.title}")
        print(f"  State: {event.open_state} | Location: {event.location}")
        print(f"  Submission start: {event.start_date} | Submission deadline: {event.deadline}")
        print(f"  Submission period: {event.submission_period}")
        print(f"  Themes: {', '.join(event.themes) or '-'}")
        print(f"  Prize: {event.prize or '-'}")
        print(f"  {event.url}")
    if result.preview_day is not None:
        print(f"\nReminder preview for {result.preview_day} ({result.timezone}): {len(result.preview)} pending")
        for reminder in result.preview:
            print(f"\n{format_reminder(reminder)}")
    if result.delivery is not None:
        delivered = result.delivery
        print(f"\nTelegram reminders: {delivered.sent} sent, {delivered.failed} failed, {delivered.skipped} skipped")
    if result.export_delivery is not None:
        print(f"\nCSV export: {result.export_delivery.status} ({result.export_delivery.count} hackathons)")


def main() -> int:
    """Run the application and translate failures into CLI exit codes."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = load_config(args.config)
        mode = "send" if args.send_reminders else "preview" if args.preview_reminders else "list"
        result = run(config, mode=mode, offline=args.offline, database_path=args.db,
                     today=args.today, send_export=args.send_export)
    except (OSError, ValueError, FetchError, requests.RequestException, sqlite3.Error) as exc:
        logging.error("Unable to sync hackathons: %s", exc)
        return 1
    print_result(result)
    reminder_failed = result.delivery is not None and result.delivery.failed > 0
    export_failed = result.export_delivery is not None and result.export_delivery.status == "failed"
    return 1 if reminder_failed or export_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
