"""List Devpost hackathons matching the configured filters."""

import argparse
import logging
from pathlib import Path
import sys

import requests

from config import load_config
from fetch import FetchError, fetch_hackathons, load_snapshot, matches, plain_text


def main() -> int:
    """Print matching events, or exit nonzero on incomplete retrieval."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    parser.add_argument("--offline", type=Path, help="Read a saved page without network access")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = load_config(args.config)
        items = load_snapshot(args.offline) if args.offline else fetch_hackathons(config)
        selected = [item for item in items if matches(item, config)]
    except (OSError, ValueError, FetchError, requests.RequestException) as exc:
        logging.error("Unable to list hackathons: %s", exc)
        return 1
    print(f"Matching hackathons: {len(selected)} / {len(items)} fetched")
    for item in selected:
        print(f"\n[{item['id']}] {plain_text(item['title'])}")
        print(f"  State: {item['open_state']} | Location: {plain_text(item['displayed_location']['location'])}")
        print(f"  Submission period: {item['submission_period_dates']}")
        print(f"  Themes: {', '.join(plain_text(t['name']) for t in item['themes']) or '-'}")
        print(f"  Prize: {plain_text(item['prize_amount']) or '-'}")
        print(f"  {item['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
