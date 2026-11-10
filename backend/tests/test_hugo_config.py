"""
Tests: string-level hugo.toml editor (allowed keys only, rest untouched).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hugo_config

SAMPLE = """baseURL = 'https://proton-org-rs.github.io/vss-hugo/'

[params]
description = "Opis sajta"
brandLogo = "/images/brand/logo-vss-uss.png"
ogImage = "/images/original/alumni-hero.jpg"
joinFormUrl = "https://forms.gle/xyz"

[params.contact]
email = "stari@mail.com"
linkedin = "https://www.linkedin.com/"
instagram = "https://instagram.com/x"

[module.mounts]
source = "content"
target = "content"
"""


class TestHugoConfig(unittest.TestCase):
    def test_read_params(self):
        data = hugo_config.read_allowed_params(SAMPLE)
        self.assertEqual(data["params"]["description"], "Opis sajta")
        self.assertEqual(data["contact"]["email"], "stari@mail.com")

    def test_edit_keeps_untouched_lines(self):
        new = hugo_config.edit_allowed_params(
            SAMPLE, {"contact": {"email": "novi@mail.com"}}
        )
        self.assertIn('email = "novi@mail.com"', new)
        self.assertIn("[module.mounts]", new)
        self.assertIn("source = \"content\"", new)
        self.assertIn("baseURL", new)

    def test_unknown_key_ignored(self):
        new = hugo_config.edit_allowed_params(
            SAMPLE, {"params": {"evil": "x", "description": "Novi opis"}}
        )
        self.assertNotIn("evil", new)
        self.assertIn('description = "Novi opis"', new)

    def test_missing_section_appended(self):
        text = "baseURL = 'x'\n"
        new = hugo_config.edit_allowed_params(
            text, {"contact": {"email": "a@b.c"}}
        )
        self.assertIn("[params.contact]", new)
        self.assertIn('email = "a@b.c"', new)

    def test_missing_key_inserted(self):
        text = "[params]\ndescription = \"x\"\n\n[module.mounts]\nsource = \"content\"\n"
        new = hugo_config.edit_allowed_params(text, {"params": {"ogImage": "/i/x.jpg"}})
        self.assertIn('ogImage = "/i/x.jpg"', new)
        # description stays
        self.assertIn('description = "x"', new)


if __name__ == "__main__":
    unittest.main()
