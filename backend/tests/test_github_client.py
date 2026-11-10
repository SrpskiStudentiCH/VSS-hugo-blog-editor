"""
Tests: GitHub client edge cases (directory responses, error mapping).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from github_client import GitHubClient, GitHubError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"ok", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class TestContentsMeta(unittest.TestCase):
    def setUp(self):
        self.client = GitHubClient("token", "owner", "repo")

    def test_directory_response_raises_clear_error(self):
        # GitHub returns a LIST for directories — must not crash with
        # "'list' object has no attribute 'get'".
        with patch.object(
            self.client._session,
            "request",
            return_value=FakeResponse(payload=[{"name": "a.md", "type": "file"}]),
        ):
            with self.assertRaises(GitHubError) as ctx:
                self.client.get_contents_meta("/")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("direktorijum", ctx.exception.message)

    def test_file_response(self):
        payload = {
            "sha": "abc",
            "size": 10,
            "encoding": "base64",
            "content": "aGVsbG8=",
        }
        with patch.object(
            self.client._session,
            "request",
            return_value=FakeResponse(payload=payload),
        ):
            meta = self.client.get_contents_meta("content/x.md")
        self.assertEqual(meta["sha"], "abc")
        self.assertEqual(meta["content_b64"], "aGVsbG8=")

    def test_rate_limit_message(self):
        with patch.object(
            self.client._session,
            "request",
            return_value=FakeResponse(
                status_code=403,
                payload={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2000000000"},
            ),
        ):
            with self.assertRaises(GitHubError) as ctx:
                self.client.get_contents_meta("content/x.md")
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("rate limit", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
