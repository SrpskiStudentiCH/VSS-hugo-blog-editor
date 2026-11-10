"""
Line diff (LCS-based) and commit message helpers.
"""
from difflib import SequenceMatcher


def line_diff(old_text, new_text):
    """
    Diff two texts line by line. Returns a list of ops:
        {"type": "equal"|"del"|"add", "text": str}
    """
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()
    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    ops = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.extend({"type": "equal", "text": line} for line in old_lines[i1:i2])
        elif tag == "delete":
            ops.extend({"type": "del", "text": line} for line in old_lines[i1:i2])
        elif tag == "insert":
            ops.extend({"type": "add", "text": line} for line in new_lines[j1:j2])
        else:  # replace
            ops.extend({"type": "del", "text": line} for line in old_lines[i1:i2])
            ops.extend({"type": "add", "text": line} for line in new_lines[j1:j2])
    return ops


def action_label(op, section):
    """Human-readable action label for a pending operation."""
    if op == "create":
        return "dodaje"
    if op == "delete":
        return "briše"
    if section in ("events", "blog"):
        return "menja"
    return "ažurira"


def commit_message(section, action, title):
    """
    Template: content(events): <akcija> "<naslov>" [admin-tool]
    """
    title = (title or "").replace('"', "'").strip()
    if title:
        return f'content({section}): {action_label(action, section)} "{title}" [admin-tool]'
    return f"content({section}): {action_label(action, section)} [admin-tool]"


def suggest_commit_message(ops):
    """Suggest one commit message for a batch of pending operations."""
    if not ops:
        return "admin-tool: bez izmena"
    first = ops[0]
    section = _section_of_path(first["path"])
    if len(ops) == 1:
        title = _title_of(first)
        return commit_message(section, first["op"], title)
    creates = [o for o in ops if o["op"] == "create"]
    deletes = [o for o in ops if o["op"] == "delete"]
    if creates and not deletes:
        title = _title_of(creates[0])
        return f"content({section}): dodaje {len(creates)} fajlova" + (
            f' — "{title}"' if title else ""
        ) + " [admin-tool]"
    if deletes and not creates:
        return f"content({section}): briše {len(deletes)} fajlova [admin-tool]"
    return f"content({section}): izmena ({len(ops)} fajlova) [admin-tool]"


def _section_of_path(path):
    path = path or ""
    if "/events/" in path:
        return "events"
    if "/blog/" in path:
        return "blog"
    if path.endswith("board.md"):
        return "board"
    if "/documents/" in path:
        return "documents"
    if path == "hugo.toml":
        return "settings"
    if path.startswith("i18n/"):
        return "i18n"
    if path.startswith("static/"):
        return "media"
    return "content"


def _title_of(op):
    text = op.get("content")
    if not text:
        return None
    try:
        from markdown_parser import parse_front_matter

        front = parse_front_matter(text)
        return front.get("title") or None
    except Exception:
        return None
