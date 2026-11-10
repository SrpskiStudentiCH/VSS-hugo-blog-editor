"""
Tests: comment-preserving i18n YAML editor.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml_i18n

SAMPLE = """# Navigacija
nav_home: "Početna"
nav_events: "Događaji"

# Događaji
events_upcoming: "Predstojeći" # inline komentar
events_past: "Prošli"

lists:
  one: "a"
  two: "b"
"""


class TestYamlI18n(unittest.TestCase):
    def test_set_value_preserves_comments(self):
        new = yaml_i18n.set_value(SAMPLE, "nav_home", "Dom")
        self.assertIn("# Navigacija", new)
        self.assertIn('nav_home: "Dom"', new)
        self.assertIn('nav_events: "Događaji"', new)

    def test_inline_comment_preserved(self):
        new = yaml_i18n.set_value(SAMPLE, "events_upcoming", "Sledeći")
        self.assertIn('events_upcoming: "Sledeći" # inline komentar', new)

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            yaml_i18n.set_value(SAMPLE, "nepostojeci", "x")

    def test_dotted_path(self):
        new = yaml_i18n.set_value(SAMPLE, "lists.two", "c")
        self.assertIn('two: "c"', new)
        self.assertIn('one: "a"', new)

    def test_flat_keys(self):
        keys = yaml_i18n.extract_flat_keys(SAMPLE)
        self.assertIn("nav_home", keys)
        self.assertIn("lists.one", keys)
        self.assertNotIn("#", "".join(keys))

    def test_read_all(self):
        values = yaml_i18n.read_all(SAMPLE)
        self.assertEqual(values["nav_home"], "Početna")
        self.assertEqual(values["events_past"], "Prošli")

    def test_list_value_roundtrip(self):
        text = 'tags: ["a", "b"]\n'
        new = yaml_i18n.set_value(text, "tags", ["a", "b", "c"])
        self.assertIn('tags: ["a", "b", "c"]', new)


if __name__ == "__main__":
    unittest.main()
