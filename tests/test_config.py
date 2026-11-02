"""Check database path resolution and reject invalid storage settings."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from config import load_config


class ConfigTests(unittest.TestCase):
    def test_database_path_is_relative_to_config_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('database_path = "state/bot.sqlite3"\n', encoding="utf-8")
            self.assertEqual(load_config(path).database_path, path.parent / "state" / "bot.sqlite3")

    def test_default_path_uses_config_directory(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("", encoding="utf-8")
            self.assertEqual(load_config(path).database_path, path.parent / "data" / "hackathons.sqlite3")

    def test_invalid_database_path_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            for value in ('""', '"  "', '42', '[]'):
                with self.subTest(value=value):
                    path.write_text(f"database_path = {value}\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "database_path"):
                        load_config(path)

    def test_unknown_timezone_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('timezone = "Invalid/Timezone"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown timezone"):
                load_config(path)
