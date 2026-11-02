"""Exercise filters and network policy with fake responses only."""

import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock, patch

import requests

from config import Config, HttpConfig
from fetch import DevpostClient, FetchError, matches, plain_text, validate_page


def response(data, status=200, headers=None):
    """Create an in-memory HTTP response."""
    result = requests.Response()
    result.status_code = status
    result._content = (data if isinstance(data, str) else json.dumps(data)).encode()
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "id": 1, "title": "Build AI agents", "url": "https://example.com/",
            "open_state": "open", "displayed_location": {"location": "Online"},
            "submission_period_dates": "Nov 01 - 09, 2026",
            "prize_amount": "$<span>100</span>",
            "themes": [{"id": 6, "name": "Machine Learning/AI"}],
            "organization_name": "Example",
        }

    def client(self, replies, **http):
        session = Mock()
        session.get.side_effect = replies
        return DevpostClient(Config(http=HttpConfig(**http)), session)

    def test_combined_filters_and_case_insensitive_keyword(self):
        config = Config(themes=("machine learning/ai",), keywords=("AGENT", "python"))
        self.assertTrue(matches(self.item, config))
        other = copy.deepcopy(self.item)
        other["displayed_location"]["location"] = "London"
        self.assertFalse(matches(other, config))
        self.assertTrue(matches(other, replace(config, online_only=False)))
        self.assertFalse(matches(self.item, replace(config, themes=("AR/VR",))))
        self.assertFalse(matches(self.item, replace(config, statuses=("upcoming",))))

    def test_prize_html_is_removed(self):
        self.assertEqual(plain_text("$<span data-currency-value>67,500</span> &amp; prizes"), "$67,500 & prizes")

    def test_changed_schema_fails_explicitly(self):
        with self.assertRaisesRegex(FetchError, "invalid themes"):
            validate_page({"hackathons": [{**self.item, "themes": None}], "meta": {"total_count": 1, "per_page": 40}})

    @patch("fetch.time.sleep")
    def test_server_page_size_and_duplicate_ids(self, sleep):
        other = {**self.item, "id": 2}
        client = self.client([
            response("User-agent: *\nDisallow:\n"),
            response({"hackathons": [self.item], "meta": {"total_count": 3, "per_page": 1}}),
            response({"hackathons": [self.item], "meta": {"total_count": 3, "per_page": 1}}),
        ])
        with self.assertRaisesRegex(FetchError, "no progress"):
            client.fetch()
        client = self.client([
            response("User-agent: *\nDisallow:\n"),
            response({"hackathons": [self.item], "meta": {"total_count": 2, "per_page": 1}}),
            response({"hackathons": [other], "meta": {"total_count": 2, "per_page": 1}}),
        ])
        self.assertEqual([h["id"] for h in client.fetch()], [1, 2])
        self.assertEqual(client.session.get.call_count, 3)
        self.assertTrue(sleep.called)

    def test_robots_denial_prevents_listing_request(self):
        client = self.client([response("User-agent: *\nDisallow: /api/\n")])
        with self.assertRaisesRegex(FetchError, "robots"):
            client.fetch()
        self.assertEqual(client.session.get.call_count, 1)

    def test_long_rate_limit_is_not_retried_early(self):
        client = self.client([response("", 429, {"Retry-After": "3600"})])
        with self.assertRaisesRegex(FetchError, "wait limit"):
            client.fetch()
        self.assertEqual(client.session.get.call_count, 1)

    @patch("fetch.time.sleep")
    def test_bounded_rate_limit_retry(self, sleep):
        client = self.client([
            response("", 429, {"Retry-After": "3"}),
            response("User-agent: *\nDisallow:\n"),
            response({"hackathons": [], "meta": {"total_count": 0, "per_page": 40}}),
        ])
        self.assertEqual(client.fetch(), [])
        sleep.assert_any_call(3.0)

    @patch("fetch.time.sleep")
    def test_page_limit_rejects_partial_results(self, sleep):
        client = self.client([
            response("User-agent: *\nDisallow:\n"),
            response({"hackathons": [self.item], "meta": {"total_count": 2, "per_page": 1}}),
        ], max_pages=1)
        with self.assertRaisesRegex(FetchError, "Page limit"):
            client.fetch()


if __name__ == "__main__":
    unittest.main()
