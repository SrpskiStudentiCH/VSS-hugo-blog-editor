"""
Tests: diff + commit message templates.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diff_utils import commit_message, line_diff, suggest_commit_message


class TestLineDiff(unittest.TestCase):
    def test_no_change(self):
        ops = line_diff("a\nb", "a\nb")
        self.assertTrue(all(o["type"] == "equal" for o in ops))

    def test_add_and_remove(self):
        ops = line_diff("a\nb", "a\nc")
        types = [o["type"] for o in ops]
        self.assertEqual(types, ["equal", "del", "add"])
        self.assertEqual([o["text"] for o in ops if o["type"] == "del"], ["b"])
        self.assertEqual([o["text"] for o in ops if o["type"] == "add"], ["c"])

    def test_create_diff(self):
        ops = line_diff("", "x\ny")
        self.assertEqual([o["type"] for o in ops], ["add", "add"])

    def test_delete_diff(self):
        ops = line_diff("x\ny", "")
        self.assertEqual([o["type"] for o in ops], ["del", "del"])


class TestCommitMessages(unittest.TestCase):
    def test_event_create(self):
        self.assertEqual(
            commit_message("events", "create", "Dobrodošlica"),
            'content(events): dodaje "Dobrodošlica" [admin-tool]',
        )

    def test_board_update(self):
        self.assertEqual(
            commit_message("board", "update", ""),
            "content(board): ažurira [admin-tool]",
        )

    def test_suggest_single(self):
        ops = [
            {"op": "create", "path": "content/events/x.md", "content": '+++\ntitle = "A"\n+++\n'}
        ]
        self.assertIn('"A"', suggest_commit_message(ops))

    def test_suggest_multi_delete(self):
        ops = [
            {"op": "delete", "path": "content/events/a.md", "sha": "s1"},
            {"op": "delete", "path": "content/en/events/a.md", "sha": "s2"},
        ]
        msg = suggest_commit_message(ops)
        self.assertIn("events", msg)
        self.assertIn("2 fajlova", msg)


if __name__ == "__main__":
    unittest.main()
