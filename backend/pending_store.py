"""
In-memory "pending changes" store.

Every edit goes here first; nothing is pushed to GitHub until the user
confirms the aggregated preview and commits. Ops are merged per path
(a new op on the same path replaces the previous one).
"""
import time
import uuid

# Path prefix -> content section for validation/messages.
SECTION_RULES = (
    ("content/events/", "events"),
    ("content/en/events/", "events"),
    ("content/de/events/", "events"),
    ("content/blog/", "blog"),
    ("content/en/blog/", "blog"),
    ("content/de/blog/", "blog"),
)


def section_of_path(path):
    for prefix, section in SECTION_RULES:
        if path.startswith(prefix) and path.endswith(".md"):
            return section
    return None


class PendingStore:
    def __init__(self):
        self._ops = []  # ordered list of ops

    def add(self, ops, base_sha=None):
        """Add ops; replaces any existing op with the same path."""
        for op in ops:
            existing = [o for o in self._ops if o["path"] == op["path"]]
            for old in existing:
                self._ops.remove(old)
            self._ops.append(
                {
                    "id": uuid.uuid4().hex[:10],
                    "op": op.get("op"),  # create | update | delete
                    "path": op.get("path"),
                    "content": op.get("content"),  # text files
                    "content_b64": op.get("content_b64"),  # binary files
                    "sha": op.get("sha"),  # base sha (from read time)
                    "added_at": int(time.time()),
                }
            )
        if base_sha:
            self.base_sha = base_sha

    def remove(self, op_id):
        before = len(self._ops)
        self._ops = [o for o in self._ops if o["id"] != op_id]
        return before != len(self._ops)

    def list(self):
        return list(self._ops)

    def clear(self):
        self._ops = []
        self.base_sha = None

    @property
    def base_sha(self):
        return getattr(self, "_base_sha", None)

    @base_sha.setter
    def base_sha(self, value):
        self._base_sha = value

    def to_commit_entries(self):
        """Convert ops into Git Data API tree entries (path -> blob sha)."""
        return list(self._ops)


_store = PendingStore()


def get_store():
    return _store
