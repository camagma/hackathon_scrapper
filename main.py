"""Fetch, store, and list Devpost hackathons matching configured filters."""

import argparse
import logging
from pathlib import Path
import sqlite3
import sys

import requests

from config import load_config
from fetch import FetchError, fetch_hackathons, load_snapshot, matches
from storage import normalize, open_database, upsert_hackathons


def main() -> int:
    """Print matching events, or exit nonzero on incomplete retrieval."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    parser.add_argument("--offline", type=Path, help="Read a saved page without network access")
    parser.add_argument("--db", type=Path, help="Override database path (relative to current directory)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = load_config(args.config)
        items = load_snapshot(args.offline) if args.offline else fetch_hackathons(config)
        selected_ids = {item["id"] for item in items if matches(item, config)}
        # Parse the entire batch before opening or changing persistent state.
        events = [normalize(item) for item in items]
        database_path = args.db.expanduser() if args.db is not None else config.database_path
        with open_database(database_path) as connection:
            result = upsert_hackathons(connection, events, complete_snapshot=args.offline is None)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
