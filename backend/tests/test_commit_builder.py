"""
Tests: atomic Git Data commit builder (blob -> tree -> commit -> ref) and
conflict detection, using a stub GitHub client.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import repo_service
from github_client import GitHubError
from pending_store import PendingStore

EVENT_TEXT = """+++
title = "Test događaj"
date = 2026-10-01
draft = false
event_type = "social"
semester = "Jesenji semestar 2026"
+++

Telo.
"""


class FakeClient:
    branch = "main"

    def __init__(self, head="head1"):
        self.head = head
        self.blobs = []
        self.tree_entries = None
        self.committed = None
        self.ref_update = None

    def get_head(self):
        return self.head

    def get_commit_meta(self, sha):
        return {"sha": sha, "tree_sha": "tree1", "parents": [], "message": ""}

    def create_blob(self, content):
        self.blobs.append(content)
        return f"blob{len(self.blobs)}"

    def create_tree(self, base_tree_sha, entries):
        self.tree_entries = entries
        return "tree2"

    def create_commit(self, message, tree_sha, parent_sha):
        self.committed = (message, tree_sha, parent_sha)
        return "commit2"

    def update_ref(self, ref, sha):
        self.ref_update = (ref, sha)

    def invalidate_cache(self):
        pass


class TestCommitBuilder(unittest.TestCase):
    def _store(self):
        store = PendingStore()
        store.add(
            [
                {
                    "op": "create",
                    "path": "content/events/2026-10-01-test.md",
                    "content": EVENT_TEXT,
                },
                {
                    "op": "update",
                    "path": "content/en/events/2026-10-01-test.md",
                    "content": EVENT_TEXT,
                    "sha": "sha-en",
                },
                {
                    "op": "delete",
                    "path": "content/de/events/2026-10-01-test.md",
                    "sha": "sha-de",
                },
            ],
            base_sha="head1",
        )
        return store

    def test_atomic_commit(self):
        fake = FakeClient()
        store = self._store()
        result = repo_service.commit_pending(fake, store, None)
        self.assertEqual(result["sha"], "commit2")
        # 2 blobs (create + update), delete needs no blob
        self.assertEqual(len(fake.blobs), 2)
        self.assertEqual(
            [e["path"] for e in fake.tree_entries],
            [
                "content/events/2026-10-01-test.md",
                "content/en/events/2026-10-01-test.md",
                "content/de/events/2026-10-01-test.md",
            ],
        )
        entries = {e["path"]: e for e in fake.tree_entries}
        self.assertTrue(entries["content/events/2026-10-01-test.md"]["sha"].startswith("blob"))
        self.assertIsNone(entries["content/de/events/2026-10-01-test.md"]["sha"])
        # commit parent is the base head, ref moved to the new commit
        self.assertEqual(fake.committed[2], "head1")
        self.assertEqual(fake.ref_update, ("main", "commit2"))
        self.assertIn("[admin-tool]", fake.committed[0])
        # store is emptied after commit
        self.assertEqual(store.list(), [])

    def test_conflict_detected(self):
        fake = FakeClient(head="head2")  # branch moved since read
        store = self._store()
        with self.assertRaises(repo_service.ConflictError):
            repo_service.commit_pending(fake, store, None)

    def test_validation_blocks_commit(self):
        fake = FakeClient()
        store = PendingStore()
        store.add(
            [{"op": "create", "path": "README.md", "content": "x"}],
            base_sha="head1",
        )
        with self.assertRaises(GitHubError) as ctx:
            repo_service.commit_pending(fake, store, None)
        self.assertIn("allow", ctx.exception.message)

    def test_custom_message(self):
        fake = FakeClient()
        store = self._store()
        repo_service.commit_pending(fake, store, "Custom [admin-tool]")
        self.assertTrue(fake.committed[0].startswith("Custom"))


if __name__ == "__main__":
    unittest.main()
