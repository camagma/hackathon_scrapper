"""Check CLI persistence and failure boundaries without network requests."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devpost_reminder.fetch import FetchError
from devpost_reminder.cli import main
from devpost_reminder.storage import list_hackathons, open_database


class MainTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "devpost_reminder.config.toml"
        self.config.write_text('keywords = ["agent"]\n', encoding="utf-8")
        self.db = root / "bot.sqlite3"
        self.snapshot = root / "snapshot.json"
        self.items = [
            {"id": number, "title": title, "url": "https://example.com/",
             "submission_period_dates": "Nov 01 - 09, 2026", "themes": [],
             "prize_amount": "", "open_state": "open",
             "displayed_location": {"location": "Online"}}
            for number, title in ((1, "Agent challenge"), (2, "Science challenge"))
        ]

    def run_cli(self, offline=True):
        self.snapshot.write_text(json.dumps({"hackathons": self.items,
                                            "meta": {"total_count": 2, "per_page": 40}}), encoding="utf-8")
        args = ["devpost_reminder.cli.py", "--config", str(self.config), "--db", str(self.db)]
        if offline:
            args.extend(["--offline", str(self.snapshot)])
        output = io.StringIO()
        with patch("sys.argv", args), redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    @patch("requests.Session", side_effect=AssertionError("Network is forbidden"))
    def test_repeat_offline_sync_stores_all_fetched_events_but_prints_only_matches(self, session):
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("2 new, 0 refreshed", output)
        self.assertIn("Agent challenge", output)
        self.assertNotIn("Science challenge", output)
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("0 new, 2 refreshed", output)
        with open_database(self.db) as db:
            self.assertEqual(len(list_hackathons(db)), 2)

    def test_bad_date_does_not_partially_update_existing_database(self):
        self.assertEqual(self.run_cli()[0], 0)
        self.items[0]["title"] = "Changed agent title"
        self.items[1]["submission_period_dates"] = "TBD"
        with self.assertLogs(level="ERROR"):
            code, output = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        with open_database(self.db) as db:
            self.assertEqual(list_hackathons(db)[0].title, "Agent challenge")

    def test_incomplete_fetch_does_not_deactivate_previous_snapshot(self):
        self.assertEqual(self.run_cli()[0], 0)
        with patch("devpost_reminder.app.fetch_hackathons", side_effect=FetchError("Incomplete listing")):
            with self.assertLogs(level="ERROR"):
                self.assertEqual(self.run_cli(offline=False)[0], 1)
        with open_database(self.db) as db:
            self.assertEqual(len(list_hackathons(db, current_only=True)), 2)


if __name__ == "__main__":
    unittest.main()
