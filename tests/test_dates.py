"""Check calendar ranges and reject ambiguous or impossible dates."""

from datetime import date
import unittest

from devpost_reminder.dates import parse_submission_period


class DateTests(unittest.TestCase):
    def test_observed_formats(self):
        cases = [
            ("Oct 01 - Nov 12, 2026", date(2026, 10, 1), date(2026, 11, 12)),
            ("Nov 09 - 30, 2026", date(2026, 11, 9), date(2026, 11, 30)),
            ("Dec 19, 2026 - Jan 18, 2027", date(2026, 12, 19), date(2027, 1, 18)),
            ("Dec 31, 2026", date(2026, 12, 31), date(2026, 12, 31)),
        ]
        for raw, start, deadline in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_submission_period(raw), (start, deadline))

    def test_missing_start_year_across_new_year(self):
        self.assertEqual(
            parse_submission_period("Dec 19 - Jan 18, 2027"),
            (date(2026, 12, 19), date(2027, 1, 18)),
        )

    def test_leap_day_and_whitespace(self):
        self.assertEqual(
            parse_submission_period(" Feb\u00a028  –  Mar 01, 2028 "),
            (date(2028, 2, 28), date(2028, 3, 1)),
        )
        self.assertEqual(parse_submission_period("Feb 29, 2028")[1], date(2028, 2, 29))

    def test_invalid_or_unknown_dates_are_not_guessed(self):
        for raw in (
            "Feb 29, 2027", "Nov 31, 2026", "Nov 20 - 09, 2026",
            "Dec 19, 2027 - Jan 18, 2027", "Foo 01, 2026",
            "10 days left", "Nov 01 - 09", "", "Nov 09, 2026 at 5 PM",
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "Invalid submission period"):
                parse_submission_period(raw)


if __name__ == "__main__":
    unittest.main()
