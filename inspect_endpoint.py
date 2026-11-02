"""Inspect one Devpost listing page, or replay a saved JSON response."""

import argparse
import json
from pathlib import Path


ENDPOINT = "https://devpost.com/api/hackathons"
USER_AGENT = "DevpostDeadlineReminder/0.1 (public listing inspection; low volume)"


def main() -> None:
    """Print three unmodified items and all observed field names."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", type=Path, help="Read a saved response, no network")
    args = parser.parse_args()
    if args.offline:
        data = json.loads(args.offline.read_text(encoding="utf-8"))
    else:
        import requests
        from urllib.robotparser import RobotFileParser

        with requests.Session() as session:
            session.headers["User-Agent"] = USER_AGENT
            robots = session.get("https://devpost.com/robots.txt", timeout=(10, 30))
            robots.raise_for_status()
            print("robots.txt:\n", robots.text)
            policy = RobotFileParser()
            policy.parse(robots.text.splitlines())
            if not policy.can_fetch(USER_AGENT, ENDPOINT):
                raise SystemExit("robots.txt disallows the listing endpoint")
            response = session.get(ENDPOINT, params={"page": 1}, timeout=(10, 30))
            # Inspection deliberately stops on errors, including 403 and 429.
            response.raise_for_status()
            data = response.json()
            target = Path("inspection")
            target.mkdir(exist_ok=True)
            (target / "response.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (target / "robots.txt").write_text(robots.text, encoding="utf-8")
    items = data["hackathons"]
    print("Root fields:", list(data))
    print("Metadata:", json.dumps(data.get("meta"), ensure_ascii=False))
    print("Raw items:")
    print(json.dumps(items[:3], ensure_ascii=False, indent=2))
    print("Observed fields:", sorted({key for item in items for key in item}))


if __name__ == "__main__":
    main()
