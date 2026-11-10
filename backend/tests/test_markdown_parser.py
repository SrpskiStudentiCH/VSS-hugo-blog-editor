"""
Tests: markdown split/merge and TOML round-trip.
Run: python -m unittest discover -s tests -v   (from backend/)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from markdown_parser import (
    MarkdownParseError,
    build_markdown,
    merge_front_matter,
    parse_front_matter,
    parse_toml,
    serialize_front_matter,
    serialize_toml_value,
    split_front_matter,
)

SAMPLE = """+++
title = "Vidovdanski izlet"
date = 2021-07-04
draft = false
event_type = "community"
semester = "Prolećni semestar 2021"
description = "Opis."
tags = ["hiking", "vidovdan"]
members = [{ name = "Petar", role = "Predsednik" }]
+++

# Naslov

Tekst tela.
"""


class TestSplitMerge(unittest.TestCase):
    def test_split_front_matter(self):
        fm, body, err = split_front_matter(SAMPLE)
        self.assertIsNone(err)
        self.assertIn('title = "Vidovdanski izlet"', fm)
        self.assertTrue(body.startswith("# Naslov"))

    def test_split_no_front_matter(self):
        fm, body, err = split_front_matter("Samo telo.")
        self.assertIsNone(fm)
        self.assertIsNone(err)
        self.assertEqual(body, "Samo telo.")

    def test_unclosed_front_matter(self):
        with self.assertRaises(MarkdownParseError):
            split_front_matter("+++\ntitle = 'x'\n")

    def test_invalid_toml(self):
        with self.assertRaises(MarkdownParseError):
            parse_front_matter("+++\ntitle = = 'x'\n+++\ntelo\n")


class TestTomlRoundTrip(unittest.TestCase):
    def test_unknown_fields_preserved(self):
        text = "+++\nbuduce_polje = \"zadrzi me\"\ntitle = \"Staro\"\n+++\n\ntelo\n"
        new = merge_front_matter(text, {"title": "Novo"})
        self.assertIn('buduce_polje = "zadrzi me"', new)
        self.assertIn('title = "Novo"', new)
        self.assertIn("telo", new)

    def test_merge_removes_none(self):
        text = '+++\ntitle = "A"\nimage = "/images/x.jpg"\n+++\n\n'
        new = merge_front_matter(text, {"image": None})
        self.assertNotIn("image", new)
        self.assertIn('title = "A"', new)

    def test_serialize_types(self):
        data = {
            "title": "Test \"navodnici\"",
            "date": 2026,  # int stays int
            "draft": False,
            "tags": ["a", "b"],
            "table": [{"k": "v"}],
        }
        out = serialize_front_matter(data)
        self.assertIn('title = "Test \\"navodnici\\""', out)
        self.assertIn("draft = false", out)
        self.assertIn('tags = ["a", "b"]', out)
        self.assertIn('{ k = "v" }', out)

    def test_build_markdown(self):
        out = build_markdown({"title": "X", "draft": True}, "# Telo\n")
        self.assertTrue(out.startswith("+++\n"))
        self.assertIn('title = "X"', out)
        self.assertTrue(out.endswith("# Telo\n"))

    def test_date_round_trip(self):
        # tomllib parses bare dates into datetime.date; serialization must
        # produce an unquoted date so Hugo sees a real date, not a string.
        front = parse_front_matter(SAMPLE)
        self.assertEqual(front["date"].isoformat(), "2021-07-04")
        out = serialize_front_matter({"date": front["date"]})
        self.assertEqual(out, "date = 2021-07-04")


class TestNullNeverSerialized(unittest.TestCase):
    """Regression: `null` is not valid TOML and broke the Hugo deploy."""

    def test_none_becomes_empty_string(self):
        self.assertEqual(serialize_toml_value(None), '""')

    def test_none_in_inline_table(self):
        data = {"members": [{"name": "Petar", "image": None}]}
        text = serialize_front_matter(data)
        self.assertNotIn("null", text)
        parsed = parse_toml(text)  # must round-trip
        self.assertEqual(parsed["members"][0]["image"], "")

    def test_merge_with_none_image_produces_valid_toml(self):
        new = merge_front_matter(
            '+++\nlayout = "team"\nmembers = [{ name = "A", role = "R" }]\n+++\n\nTelo.\n',
            {"members": [{"name": "A", "role": "R", "email": "", "image": None}]},
        )
        self.assertNotIn("null", new)
        parsed = parse_front_matter(new)  # parses without error
        self.assertEqual(parsed["members"][0]["image"], "")


if __name__ == "__main__":
    unittest.main()
