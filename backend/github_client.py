"""
GitHub REST v3 API client used by the admin tool.

Covers:
- repo tree listing (recursive) with caching
- file read (contents + raw) with SHA
- single-file create/update/delete (Contents API)
- atomic multi-file commits (Git Data API: blobs -> tree -> commit -> ref)
- per-file commit history and workflow runs

Error mapping: 401 bad token, 403 rate limit, 404 missing, 409 conflict.
The GitHub token never leaves the server.
"""
import base64
import time

import requests

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"


class GitHubError(Exception):
    """GitHub API error with a user-friendly message."""

    def __init__(self, status, message, retry_after=None):
        self.status = status
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


class GitHubClient:
    def __init__(self, token, owner, repo, branch="main", timeout=30):
        if not token:
            raise GitHubError(401, "GITHUB_TOKEN nije postavljen (backend .env).")
        if not owner or not repo:
            raise GitHubError(400, "REPO_OWNER / REPO_NAME nisu postavljeni (backend .env).")
        self.token = token
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.timeout = timeout
        self._session = requests.Session()
        self._tree_cache = None
        self._tree_cache_at = 0.0
        self._tree_cache_ttl = 300.0  # 5 minutes

    # ------------------------------------------------------------------ utils
    @property
    def repo_url(self):
        return f"{API_BASE}/repos/{self.owner}/{self.repo}"

    def _headers(self):
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def _request(self, method, url, **kwargs):
        try:
            resp = self._session.request(
                method, url, headers=self._headers(), timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise GitHubError(0, f"GitHub API nije dostupan: {exc}") from exc

        if resp.status_code in (200, 201, 204):
            return resp
        return self._raise(resp)

    def _raise(self, resp):
        try:
            body = resp.json()
        except ValueError:
            body = {}
        detail = body.get("message") or resp.text[:200]
        status = resp.status_code
        if status == 401:
            raise GitHubError(401, "Neispravan GitHub token (401).")
        if status == 403:
            if int(resp.headers.get("X-RateLimit-Remaining", "1")) == 0:
                reset = resp.headers.get("X-RateLimit-Reset")
                when = (
                    time.strftime("%H:%M:%S", time.localtime(int(reset)))
                    if reset and reset.isdigit()
                    else "?"
                )
                raise GitHubError(403, f"GitHub rate limit dostignut — reset u {when} (UTC).")
            raise GitHubError(403, f"GitHub je odbio zahtev (403): {detail}")
        if status == 404:
            raise GitHubError(404, f"Nije pronađeno na GitHub-u: {detail}")
        if status == 409:
            raise GitHubError(409, f"Konflikt na GitHub-u (409): {detail}")
        raise GitHubError(status, f"GitHub greška ({status}): {detail}")

    def _json(self, method, url, **kwargs):
        resp = self._request(method, url, **kwargs)
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------- tree
    def get_tree(self, recursive=True, ref=None):
        """Recursive git tree for the branch. Cached for a short TTL."""
        now = time.time()
        if (
            self._tree_cache is not None
            and ref in (None, self.branch)
            and now - self._tree_cache_at < self._tree_cache_ttl
        ):
            return self._tree_cache
        ref = ref or self.branch
        data = self._json(
            "GET",
            f"{self.repo_url}/git/trees/{ref}?recursive=1",
        )
        if data.get("truncated"):
            # Fall back to Contents API listing for very large repos is out of
            # scope; the Hugo repo is small.
            pass
        entries = [
            {
                "path": e["path"],
                "mode": e.get("mode", "100644"),
                "type": e["type"],
                "sha": e["sha"],
                "size": e.get("size"),
            }
            for e in data.get("tree", [])
            if e["type"] == "blob"
        ]
        self._tree_cache = entries
        self._tree_cache_at = now
        return entries

    def invalidate_cache(self):
        self._tree_cache = None

    # ------------------------------------------------------------- contents
    def get_contents_meta(self, path, ref=None):
        """GET /contents/{path} -> {sha, size, encoding} (decoded content)."""
        data = self._json("GET", f"{self.repo_url}/contents/{path}?ref={ref or self.branch}")
        if isinstance(data, list):
            raise GitHubError(
                400,
                f"'{path}' je direktorijum, ne fajl — izaberi konkretan fajl.",
            )
        out = {
            "path": path,
            "sha": data.get("sha"),
            "size": data.get("size"),
            "encoding": data.get("encoding"),
        }
        if data.get("encoding") == "base64" and data.get("content"):
            content = data["content"].replace("\n", "")
            out["content_b64"] = content
        return out

    def read_text(self, path, ref=None):
        """Read a text file; returns (text, sha)."""
        meta = self.get_contents_meta(path, ref)
        if "content_b64" not in meta:
            return None, meta.get("sha")
        try:
            text = base64.b64decode(meta["content_b64"]).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubError(400, f"Fajl {path} nije UTF-8 tekst.") from exc
        return text, meta["sha"]

    def read_bytes(self, path, ref=None):
        """Read a binary file; returns (bytes, sha)."""
        meta = self.get_contents_meta(path, ref)
        if "content_b64" not in meta:
            return b"", meta.get("sha")
        return base64.b64decode(meta["content_b64"]), meta["sha"]

    def put_contents(self, path, content_bytes, message, sha=None):
        """Single-file create/update via Contents API."""
        payload = {
            "message": message,
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        self._json("PUT", f"{self.repo_url}/contents/{path}", json=payload)
        self.invalidate_cache()

    def delete_contents(self, path, message, sha):
        payload = {"message": message, "sha": sha, "branch": self.branch}
        self._json("DELETE", f"{self.repo_url}/contents/{path}", json=payload)
        self.invalidate_cache()

    # ------------------------------------------------------------ git data
    def get_head(self):
        """Current head commit SHA of the branch."""
        data = self._json("GET", f"{self.repo_url}/git/refs/heads/{self.branch}")
        return data["object"]["sha"]

    def get_commit_meta(self, sha):
        """Commit object: {sha, tree_sha, parents, message}."""
        data = self._json("GET", f"{self.repo_url}/git/commits/{sha}")
        return {
            "sha": data["sha"],
            "tree_sha": data["tree"]["sha"],
            "parents": [p["sha"] for p in data.get("parents", [])],
            "message": data.get("message"),
        }

    def create_blob(self, content_bytes):
        data = self._json(
            "POST",
            f"{self.repo_url}/git/blobs",
            json={
                "content": base64.b64encode(content_bytes).decode("ascii"),
                "encoding": "base64",
            },
        )
        return data["sha"]

    def create_tree(self, base_tree_sha, entries):
        """
        entries: list of dicts
          - {"path": p, "mode": "100644", "type": "blob", "sha": blob_sha}
          - {"path": p, "mode": "100644", "type": "blob", "sha": None}  (delete)
        """
        data = self._json(
            "POST",
            f"{self.repo_url}/git/trees",
            json={"base_tree": base_tree_sha, "tree": entries},
        )
        return data["sha"]

    def create_commit(self, message, tree_sha, parent_sha):
        data = self._json(
            "POST",
            f"{self.repo_url}/git/commits",
            json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        )
        return data["sha"]

    def update_ref(self, ref_name, sha):
        self._json("PATCH", f"{self.repo_url}/git/refs/heads/{ref_name}", json={"sha": sha})

    # ------------------------------------------------------------- history
    def list_commits(self, path=None, per_page=30):
        url = f"{self.repo_url}/commits?sha={self.branch}&per_page={per_page}"
        if path:
            url += f"&path={path}"
        data = self._json("GET", url)
        return [
            {
                "sha": c["sha"],
                "message": c["commit"]["message"],
                "date": c["commit"]["author"]["date"],
                "author": (c.get("author") or {}).get("login")
                or c["commit"]["author"]["name"],
            }
            for c in data
        ]

    def latest_workflow_run(self):
        """Latest GitHub Actions run (used for deploy status)."""
        data = self._json("GET", f"{self.repo_url}/actions/runs?per_page=1")
        runs = data.get("workflow_runs") or []
        if not runs:
            return None
        r = runs[0]
        return {
            "name": r.get("name") or r.get("display_title"),
            "status": r.get("status"),
            "conclusion": r.get("conclusion"),
            "head_sha": r.get("head_sha"),
            "created_at": r.get("created_at"),
            "html_url": r.get("html_url"),
        }


def raw_url(owner, repo, branch, path):
    """Public raw URL (used for image thumbnails in the UI)."""
    return f"{RAW_BASE}/{owner}/{repo}/{branch}/{path}"
