"""
Tests: validators (schemas, filenames, dates, allow-list, binary checks, i18n).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import validators as v


class TestSlugify(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(v.slugify("Dobrodošlica za nove studente"), "dobrodoslica-za-nove-studente")
        self.assertEqual(v.slugify("  Hello, World!  "), "hello-world")
        self.assertEqual(v.slugify("Žurka č š ć"), "zurka-c-s-c")


class TestFilenames(unittest.TestCase):
    def test_event_filename(self):
        self.assertIsNone(v.validate_filename("2026-09-25-dobrodoslica-za-nove-studente.md", "events"))
        self.assertIsNotNone(v.validate_filename("spring-network-night.md", "events"))
        self.assertIsNotNone(v.validate_filename("2026-9-25-slug.md", "events"))
        self.assertIsNotNone(v.validate_filename("2026-09-25-SLUG.md", "events"))

    def test_blog_filename(self):
        self.assertIsNone(v.validate_filename("welcome-to-the-network.md", "blog"))
        self.assertIsNotNone(v.validate_filename("Welcome-To.md", "blog"))


class TestDates(unittest.TestCase):
    def test_validate_date(self):
        self.assertIsNone(v.validate_date("2026-09-25"))
        self.assertIsNotNone(v.validate_date("25.09.2026"))
        self.assertIsNotNone(v.validate_date(None))

    def test_end_date_before_date(self):
        errors = v.validate_event(
            {"title": "X", "date": "2026-09-26", "end_date": "2026-09-25", "draft": False, "event_type": "social", "semester": "J"}
        )
        self.assertTrue(any("end_date" in e for e in errors))

    def test_event_required(self):
        errors = v.validate_event({"title": "X"})
        keys = " ".join(errors)
        for field in ("date", "event_type", "semester"):
            self.assertIn(field, keys)

    def test_draft_must_be_bool(self):
        errors = v.validate_event(
            {"title": "X", "date": "2026-09-25", "draft": "false", "event_type": "social", "semester": "J"}
        )
        self.assertTrue(any("draft" in e for e in errors))


class TestAllowList(unittest.TestCase):
    def test_allowed_paths(self):
        self.assertTrue(v.is_allowed_path("content/events/x.md"))
        self.assertTrue(v.is_allowed_path("i18n/sr.yaml"))
        self.assertTrue(v.is_allowed_path("static/images/events/a.jpg"))
        self.assertTrue(v.is_allowed_path("static/documents/a.pdf"))
        self.assertTrue(v.is_allowed_path("hugo.toml"))

    def test_blocked_paths(self):
        self.assertFalse(v.is_allowed_path("layouts/index.html"))
        self.assertFalse(v.is_allowed_path(".github/workflows/hugo.yml"))
        self.assertFalse(v.is_allowed_path("README.md"))
        self.assertFalse(v.is_allowed_path("archetypes/events.md"))
        self.assertFalse(v.is_allowed_path("assets/scss/main.scss"))

    def test_protected_logo(self):
        self.assertTrue(v.is_protected_delete("static/images/brand/logo-vss-uss.png"))
        self.assertFalse(v.is_protected_delete("static/images/events/x.jpg"))


class TestBinaryValidation(unittest.TestCase):
    def test_png_ok(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        self.assertIsNone(v.validate_image_bytes(png))

    def test_jpg_ok(self):
        self.assertIsNone(v.validate_image_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32))

    def test_bad_type(self):
        self.assertIsNotNone(v.validate_image_bytes(b"GIFxx" + b"\x00" * 32))

    def test_size_limit(self):
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (v.MAX_IMAGE_BYTES + 1)
        self.assertIsNotNone(v.validate_image_bytes(big))

    def test_pdf(self):
        self.assertIsNone(v.validate_document_bytes(b"%PDF-1.7 test"))
        self.assertIsNotNone(v.validate_document_bytes(b"plain text"))


class TestI18nKeys(unittest.TestCase):
    def test_equal_sets(self):
        self.assertEqual(
            v.validate_i18n_keys({"sr": ["a", "b"], "en": ["a", "b"], "de": ["a", "b"]}),
            [],
        )

    def test_missing_keys(self):
        errors = v.validate_i18n_keys({"sr": ["a", "b"], "en": ["a"], "de": ["a", "b"]})
        self.assertTrue(any("en.yaml" in e and "b" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
