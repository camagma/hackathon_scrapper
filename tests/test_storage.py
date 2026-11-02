"""Verify durable identity, reminder flags, and atomic snapshot refreshes."""

from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from storage import list_hackathons, normalize, open_database, upsert_hackathons


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state" / "test.sqlite3"
        self.event = normalize({
            "id": 1, "title": "AI &amp; science", "url": "https://example.com/",
            "submission_period_dates": "Nov 01 - 09, 2026",
            "themes": [{"name": "Machine Learning/AI"}, {"name": "Наука"}],
            "prize_amount": "$<span>100</span>", "open_state": "open",
            "displayed_location": {"location": "Online"}, "organization_name": "Example",
        })

    def test_repeated_sync_and_reopen_do_not_duplicate(self):
        with open_database(self.path) as db:
            self.assertEqual(upsert_hackathons(db, [self.event, self.event]).inserted, 1)
        with open_database(self.path) as db:
            result = upsert_hackathons(db, [self.event])
            self.assertEqual((result.inserted, result.refreshed), (0, 1))
            self.assertEqual(list_hackathons(db), [self.event])

    def test_metadata_and_changed_deadline_preserve_both_reminder_flags(self):
        with open_database(self.path) as db:
            upsert_hackathons(db, [self.event])
            with db:
                db.execute("UPDATE hackathons SET reminded_7d = 1, reminded_1d = 1 WHERE id = 1")
        changed = replace(self.event, title="Updated title", deadline=date(2026, 11, 12),
                          submission_period="Nov 01 - 12, 2026", themes=("New theme",), prize="€200")
        with open_database(self.path) as db:
            upsert_hackathons(db, [changed], complete_snapshot=True)
            self.assertEqual(list_hackathons(db), [replace(changed, reminded_7d=True, reminded_1d=True)])

    def test_complete_snapshot_retains_history_and_reappearance_flags(self):
        other = replace(self.event, id=2)
        with open_database(self.path) as db:
            upsert_hackathons(db, [self.event, other], complete_snapshot=True)
            with db:
                db.execute("UPDATE hackathons SET reminded_7d = 1 WHERE id = 1")
            upsert_hackathons(db, [other], complete_snapshot=True)
            self.assertEqual([e.id for e in list_hackathons(db, current_only=True)], [2])
            self.assertEqual(len(list_hackathons(db)), 2)
            upsert_hackathons(db, [self.event, other], complete_snapshot=True)
            self.assertTrue(list_hackathons(db, current_only=True)[0].reminded_7d)

    def test_partial_snapshot_never_deactivates_missing_events(self):
        with open_database(self.path) as db:
            upsert_hackathons(db, [self.event, replace(self.event, id=2)])
            upsert_hackathons(db, [self.event])
            self.assertEqual(len(list_hackathons(db, current_only=True)), 2)
            upsert_hackathons(db, [], complete_snapshot=True)
            self.assertEqual(list_hackathons(db, current_only=True), [])
            self.assertEqual(len(list_hackathons(db)), 2)

    def test_failed_batch_rolls_back_metadata_and_membership(self):
        with open_database(self.path) as db:
            upsert_hackathons(db, [self.event])
            with self.assertRaises(sqlite3.IntegrityError):
                upsert_hackathons(db, [replace(self.event, title="Changed"),
                                      replace(self.event, id=2, title=None)], complete_snapshot=True)
            self.assertEqual(list_hackathons(db), [self.event])

    def test_read_order_is_deadline_then_id(self):
        with open_database(self.path) as db:
            upsert_hackathons(db, [replace(self.event, id=3), self.event,
                                  replace(self.event, id=2, deadline=date(2026, 11, 2))])
            self.assertEqual([e.id for e in list_hackathons(db)], [2, 1, 3])

    def test_normalization_preserves_unicode_and_removes_html(self):
        self.assertEqual(self.event.title, "AI & science")
        self.assertEqual(self.event.prize, "$100")
        self.assertEqual(self.event.themes, ("Machine Learning/AI", "Наука"))
        self.assertEqual(self.event.start_date, date(2026, 11, 1))

    def test_future_schema_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(ValueError, "Unsupported database schema"):
            with open_database(self.path):
                self.fail("Unsupported schema opened")


if __name__ == "__main__":
    unittest.main()
