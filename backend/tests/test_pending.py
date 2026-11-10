"""
Tests: pending store merging + pending op validation.
"""
import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import repo_service
from github_client import GitHubError
from pending_store import PendingStore


class FakeReadClient:
    """Stub with read_text that succeeds or fails per path."""

    branch = "main"

    def __init__(self, texts):
        self.texts = texts  # path -> text or Exception

    def read_text(self, path, ref=None):
        value = self.texts[path]
        if isinstance(value, Exception):
            raise value
        return value, "sha-" + path

EVENT_TEXT = """+++
title = "Test događaj"
date = 2026-10-01
draft = false
event_type = "social"
semester = "Jesenji semestar 2026"
description = "Opis"
+++

Telo.
"""


class TestPendingStore(unittest.TestCase):
    def test_add_and_merge_same_path(self):
        store = PendingStore()
        store.add([{"op": "create", "path": "content/events/a.md", "content": "x"}])
        store.add([{"op": "update", "path": "content/events/a.md", "content": "y", "sha": "s"}])
        self.assertEqual(len(store.list()), 1)
        self.assertEqual(store.list()[0]["content"], "y")

    def test_remove_and_clear(self):
        store = PendingStore()
        store.add([{"op": "create", "path": "content/events/a.md", "content": "x"}])
        op_id = store.list()[0]["id"]
        self.assertTrue(store.remove(op_id))
        self.assertEqual(store.list(), [])
        store.add([{"op": "create", "path": "b.md", "content": "x"}])
        store.clear()
        self.assertEqual(store.list(), [])


class TestValidatePendingOp(unittest.TestCase):
    def test_valid_event_create(self):
        errors, _ = repo_service.validate_pending_op(
            None, {"op": "create", "path": "content/events/2026-10-01-test.md", "content": EVENT_TEXT}
        )
        self.assertEqual(errors, [])

    def test_invalid_toml_blocks(self):
        errors, _ = repo_service.validate_pending_op(
            None, {"op": "create", "path": "content/events/2026-10-01-test.md", "content": "+++\ntitle = = 'x'\n+++\n"}
        )
        self.assertTrue(any("TOML" in e for e in errors))

    def test_missing_required_field(self):
        errors, _ = repo_service.validate_pending_op(
            None,
            {
                "op": "create",
                "path": "content/events/2026-10-01-test.md",
                "content": "+++\ntitle = \"X\"\n+++\n",
            },
        )
        self.assertTrue(errors)

    def test_path_not_allowed(self):
        errors, _ = repo_service.validate_pending_op(
            None, {"op": "create", "path": "layouts/index.html", "content": "x"}
        )
        self.assertTrue(any("allow" in e for e in errors))

    def test_logo_delete_blocked(self):
        errors, _ = repo_service.validate_pending_op(
            None, {"op": "delete", "path": "static/images/brand/logo-vss-uss.png", "sha": "s"}
        )
        self.assertTrue(any("zabranjeno" in e for e in errors))

    def test_binary_image_valid(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        errors, _ = repo_service.validate_pending_op(
            None,
            {
                "op": "create",
                "path": "static/images/events/nova.png",
                "content_b64": base64.b64encode(png).decode("ascii"),
            },
        )
        self.assertEqual(errors, [])

    def test_binary_wrong_folder(self):
        pdf = b"%PDF-1.7 x"
        errors, _ = repo_service.validate_pending_op(
            None,
            {
                "op": "create",
                "path": "static/images/events/nova.pdf",
                "content_b64": base64.b64encode(pdf).decode("ascii"),
            },
        )
        self.assertTrue(errors)


class TestNonActivityMdValidation(unittest.TestCase):
    """Regression: every content .md op (board, docs, pages...) must have
    parseable TOML front matter so `null` can never break the Hugo build."""

    def test_null_in_board_md_blocked(self):
        bad = '+++\nlayout = "team"\nmembers = [{ name = "A", image = null }]\n+++\n'
        errors, _ = repo_service.validate_pending_op(
            None,
            {"op": "update", "path": "content/about/board.md", "content": bad, "sha": "s"},
        )
        self.assertTrue(any("TOML" in e or "Neispravan" in e for e in errors))

    def test_valid_board_md_passes(self):
        good = '+++\nlayout = "team"\nmembers = [{ name = "A", image = "" }]\n+++\n\nTelo.\n'
        errors, _ = repo_service.validate_pending_op(
            None,
            {"op": "update", "path": "content/en/about/board.md", "content": good, "sha": "s"},
        )
        self.assertEqual(errors, [])

    def test_null_in_docs_md_blocked(self):
        bad = '+++\nlayout = "documents"\ndocs = [{ type = "x", title = "y", url = null }]\n+++\n'
        errors, _ = repo_service.validate_pending_op(
            None,
            {"op": "update", "path": "content/documents/_index.md", "content": bad, "sha": "s"},
        )
        self.assertTrue(errors)


class TestParallelRead(unittest.TestCase):
    def test_success_and_error_paths_normalized(self):
        client = FakeReadClient(
            {
                "content/events/par-ok.md": "sadrzaj",
                "content/events/par-err.md": GitHubError(404, "nema fajla"),
            }
        )
        results = repo_service._parallel_read(
            client, ["content/events/par-ok.md", "content/events/par-err.md"]
        )
        # Every result must be a 3-tuple (text, sha, error).
        ok = results["content/events/par-ok.md"]
        self.assertEqual(ok, ("sadrzaj", "sha-content/events/par-ok.md", None))
        err = results["content/events/par-err.md"]
        self.assertEqual(err, (None, None, "nema fajla"))


if __name__ == "__main__":
    unittest.main()
