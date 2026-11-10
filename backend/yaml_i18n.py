"""
Comment-preserving editor for Hugo i18n YAML files.

Approach: line-level editing. Comments and key order are never touched; only
the value part of the matching key line is replaced. Supports:
- flat keys:      key: "value"
- dotted paths:   section:        (then, on deeper lines)
                    subkey: "value"
- list values:    key: ["a", "b"]
- inline comments after values are preserved.
"""
import re

_VALUE_LINE_RE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*:\s*)(.*)$")


def _strip_inline_comment(rest):
    in_str = False
    depth = 0
    for i, ch in enumerate(rest):
        if ch in "\"'":
            if not in_str:
                in_str = True
            elif i > 0 and rest[i - 1] != "\\":
                in_str = False
            continue
        if in_str:
            continue
        if ch in "[":
            depth += 1
        elif ch in "]":
            depth -= 1
        elif ch == "#" and depth == 0:
            return rest[:i].rstrip(), rest[i:].strip()
    return rest.rstrip(), ""


def _yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, bool):
                parts.append("true" if item else "false")
            elif isinstance(item, (int, float)):
                parts.append(str(item))
            else:
                parts.append(_yaml_scalar(str(item)))
        return "[" + ", ".join(parts) + "]"
    text = str(value)
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"')


def find_key_line(lines, path):
    """Locate (line_index, indent) for a key path like "nav.home" or "title"."""
    parts = path.split(".")
    target = parts[-1]
    if len(parts) == 1:
        for i, line in enumerate(lines):
            m = _VALUE_LINE_RE.match(line)
            if m and m.group(2) == target:
                return i, len(m.group(1))
        return None, None

    # Walk parents by indentation.
    parent_chain = parts[:-1]
    depth = 0
    current_indent = None
    for parent in parent_chain:
        found = False
        for i in range(depth, len(lines)):
            m = _VALUE_LINE_RE.match(lines[i])
            if not m:
                continue
            indent = len(m.group(1))
            if m.group(2) == parent and (
                current_indent is None or indent > current_indent
            ):
                depth = i + 1
                current_indent = indent
                found = True
                break
        if not found:
            return None, None

    # Find the final key at a deeper indentation than current_indent.
    for i in range(depth, len(lines)):
        m = _VALUE_LINE_RE.match(lines[i])
        if not m:
            continue
        indent = len(m.group(1))
        if indent <= current_indent:
            # Left the parent block.
            if indent < current_indent:
                break
            continue
        if m.group(2) == target:
            return i, indent
    return None, None


def set_value(text, path, value):
    """Replace the value of `path` preserving comments. Raises KeyError if the
    key does not exist (missing keys must be handled by the caller)."""
    lines = text.splitlines()
    idx, indent = find_key_line(lines, path)
    if idx is None:
        raise KeyError(f"i18n ključ '{path}' ne postoji.")
    m = _VALUE_LINE_RE.match(lines[idx])
    key = m.group(2)
    rest = m.group(4)
    _, comment = _strip_inline_comment(rest)
    new_value = _yaml_scalar(value)
    suffix = (" " + comment) if comment else ""
    lines[idx] = f"{' ' * indent}{key}: {new_value}{suffix}"
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def get_value(lines, path):
    idx, _ = find_key_line(lines, path)
    if idx is None:
        return None
    m = _VALUE_LINE_RE.match(lines[idx])
    raw, _ = _strip_inline_comment(m.group(4))
    if raw in ("", "null", "~"):
        return ""
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.startswith("["):
        # minimal inline list parse
        inner = raw[1:-1]
        items = []
        current = ""
        in_str = False
        for ch in inner:
            if ch in "\"'":
                in_str = not in_str
                current += ch
            elif ch == "," and not in_str:
                items.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            items.append(current.strip())
        return [i.strip('"') for i in items]
    try:
        return int(raw)
    except ValueError:
        return raw


def extract_flat_keys(text):
    """Top-level keys (flat files) or dotted paths (nested files), ordered."""
    lines = text.splitlines()
    keys = []
    stack = []  # (indent, name)
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _VALUE_LINE_RE.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        key = m.group(2)
        # strip inline comment / value check: a line is a key if it has a value
        while stack and indent <= stack[-1][0]:
            stack.pop()
        stack.append((indent, key))
        keys.append(".".join(name for _, name in stack))
    return keys


def read_all(text):
    """All key -> value pairs as dotted paths (ordered)."""
    lines = text.splitlines()
    result = {}
    for key in extract_flat_keys(text):
        result[key] = get_value(lines, key)
    return result


def set_values(text, updates):
    """Apply many updates at once (each via set_value)."""
    for path, value in updates.items():
        text = set_value(text, path, value)
    return text
