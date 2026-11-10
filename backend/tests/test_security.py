"""
Tests: security hardening.

Covers: fail-closed auth, /save auth + input validation, /api/image path and
extension guards, CORS allow-list, security headers, login throttling and the
SPA fallback path containment.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module


class SecurityTestCase(unittest.TestCase):
    def setUp(self):
        self._orig = (app_module.ADMIN_USER, app_module.ADMIN_PASS)
        app_module.ADMIN_USER, app_module.ADMIN_PASS = "admin", "secret"
        app_module._SESSIONS.clear()
        app_module._LOGIN_ATTEMPTS.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.ADMIN_USER, app_module.ADMIN_PASS = self._orig
        app_module._SESSIONS.clear()
        app_module._LOGIN_ATTEMPTS.clear()

    def _token(self):
        resp = self.client.post(
            "/login", json={"username": "admin", "password": "secret"}
        )
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()["token"]

    def _save(self, payload, token=None):
        headers = {"X-Admin-Token": token} if token else {}
        return self.client.post("/save", json=payload, headers=headers)


class TestAuthentication(SecurityTestCase):
    def test_api_requires_session(self):
        self.assertEqual(self.client.get("/api/file").status_code, 401)
        self.assertEqual(self.client.get("/api/tree").status_code, 401)
        self.assertEqual(self.client.post("/api/pending", json={"ops": []}).status_code, 401)

    def test_unknown_token_rejected(self):
        resp = self.client.get("/api/file", headers={"X-Admin-Token": "nope"})
        self.assertEqual(resp.status_code, 401)

    def test_valid_token_accepted(self):
        token = self._token()
        headers = {"X-Admin-Token": token}
        # Reaches handler validation (400 for a missing path), not auth (401).
        self.assertEqual(self.client.get("/api/file", headers=headers).status_code, 400)

    def test_expired_token_rejected(self):
        token = self._token()
        app_module._SESSIONS[token] = 0  # already expired
        resp = self.client.get("/api/file", headers={"X-Admin-Token": token})
        self.assertEqual(resp.status_code, 401)

    def test_fails_closed_without_credentials(self):
        app_module.ADMIN_USER = None
        app_module.ADMIN_PASS = None
        self.assertEqual(self.client.get("/api/file").status_code, 401)
        self.assertEqual(
            self.client.post("/login", json={"username": "", "password": ""}).status_code,
            503,
        )

    def test_login_throttled_after_repeated_failures(self):
        for _ in range(app_module._LOGIN_MAX_ATTEMPTS):
            resp = self.client.post(
                "/login", json={"username": "admin", "password": "bad"}
            )
            self.assertEqual(resp.status_code, 401)
        resp = self.client.post("/login", json={"username": "admin", "password": "bad"})
        self.assertEqual(resp.status_code, 429)


class TestSaveEndpoint(SecurityTestCase):
    def test_requires_session(self):
        resp = self._save({"slug": "ok", "front": "---\n---", "content": "body"})
        self.assertEqual(resp.status_code, 401)

    def test_rejects_path_traversal_slug(self):
        token = self._token()
        for slug in ("../pwn", "/tmp/pwn", "a/b", "UPPER", ""):
            resp = self._save(
                {"slug": slug, "front": "---\n---", "content": "body"}, token
            )
            self.assertEqual(resp.status_code, 400, slug)

    def test_rejects_non_png_image(self):
        token = self._token()
        resp = self._save(
            {
                "slug": "ok",
                "front": "---\n---",
                "content": "body",
                "image": "data:image/gif;base64,R0lGODlh",
            },
            token,
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_png_payload_with_foreign_magic_bytes(self):
        token = self._token()
        resp = self._save(
            {
                "slug": "ok",
                "front": "---\n---",
                "content": "body",
                "image": "data:image/png;base64," + "bm90IGEgcG5n",
            },
            token,
        )
        self.assertEqual(resp.status_code, 400)


class TestImageProxy(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_rejects_traversal(self):
        for path in (
            "static/images/../../secret.png",
            "static/images/..\\..\\secret.png",
            "static/images//x.png",
        ):
            resp = self.client.get("/api/image", query_string={"path": path})
            self.assertEqual(resp.status_code, 400, path)

    def test_rejects_paths_outside_allow_list(self):
        for path in ("hugo.toml", "backend/app.py", "static/x.png", "/static/images/x.png"):
            resp = self.client.get("/api/image", query_string={"path": path})
            self.assertEqual(resp.status_code, 400, path)

    def test_rejects_non_media_extensions(self):
        for path in ("static/images/x.html", "static/images/x.svg", "static/documents/x.md"):
            resp = self.client.get("/api/image", query_string={"path": path})
            self.assertEqual(resp.status_code, 400, path)


class TestCorsAndHeaders(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_cors_rejects_unknown_origin(self):
        resp = self.client.get("/api/file", headers={"Origin": "http://evil.example"})
        self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_cors_allows_dev_frontend(self):
        resp = self.client.get(
            "/api/file", headers={"Origin": "http://localhost:3000"}
        )
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://localhost:3000")

    def test_spa_response_has_security_headers(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        csp = resp.headers.get("Content-Security-Policy") or ""
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)

    def test_spa_fallback_never_serves_outside_build(self):
        for path in ("/../app.py", "/..%2fapp.py", "/static/js/../../../app.py"):
            body = self.client.get(path).get_data(as_text=True)
            self.assertNotIn("GITHUB_TOKEN", body)


if __name__ == "__main__":
    unittest.main()
