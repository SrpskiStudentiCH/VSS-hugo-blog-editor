"""
Safe string-level editor for hugo.toml.

Only keys inside [params] and [params.contact] may be edited. The rest of the
file is never touched: edits are done with line-level replacements inside the
section's line range. Missing keys are appended to the end of their section.
"""
import re

from validators import ALLOWED_HUGO_KEYS, ALLOWED_HUGO_CONTACT_KEYS, PROTECTED_HUGO_SECTIONS

_KEY_LINE_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)(\s*=\s*)(.*)$")
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _section_ranges(lines):
    """Return dict: section name -> (start_line, end_line) inclusive."""
    ranges = {}
    current = None
    current_start = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            if current is not None:
                ranges[current] = (current_start, i - 1)
            current = m.group(1).strip()
            current_start = i
    if current is not None:
        ranges[current] = (current_start, len(lines) - 1)
    return ranges


def _value_to_toml(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append('"%s"' % item.replace("\\", "\\\\").replace('"', '\\"'))
            else:
                parts.append(str(item))
        return "[" + ", ".join(parts) + "]"
    text = str(value)
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"')


def read_allowed_params(text):
    """Read editable values from hugo.toml. Returns {params: {...}, contact: {...}}."""
    lines = text.splitlines()
    ranges = _section_ranges(lines)
    result = {"params": {}, "contact": {}}

    def collect(section, keys):
        if section not in ranges:
            return
        start, end = ranges[section]
        for line in lines[start + 1 : end + 1]:
            m = _KEY_LINE_RE.match(line)
            if not m:
                continue
            key = m.group(2)
            if key not in keys:
                continue
            raw = m.group(4).strip().rstrip(",")
            raw = _strip_comment(raw)
            result[("contact" if section == "params.contact" else "params")][key] = _parse_scalar(raw)

    collect("params", ALLOWED_HUGO_KEYS)
    collect("params.contact", ALLOWED_HUGO_CONTACT_KEYS)
    return result


def _strip_comment(raw):
    in_str = False
    for i, ch in enumerate(raw):
        if ch == '"' and (i == 0 or raw[i - 1] != "\\"):
            in_str = not in_str
        elif ch == "#" and not in_str:
            return raw[:i].strip()
    return raw.strip()


def _parse_scalar(raw):
    if not raw:
        return ""
    if raw in ("true", "false"):
        return raw == "true"
    if raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        return raw


def edit_allowed_params(text, updates):
    """
    Apply updates: {"params": {...}, "contact": {...}}. Only allowed keys are
    written; the rest of the file is untouched. Protection of the other
    sections ([languages], [module.mounts], ...) is structural: this editor
    never writes outside [params] and [params.contact].
    """
    lines = text.splitlines()

    def apply(section, values, allowed):
        if not values:
            return
        values = {k: v for k, v in values.items() if k in allowed}
        if not values:
            return
        ranges = _section_ranges(lines)
        if section not in ranges:
            # Append a new section at the end of the file.
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"[{section}]")
            for key, value in values.items():
                lines.append(f"{key} = {_value_to_toml(value)}")
            return
        start, end = ranges[section]
        found = set()
        for i in range(start + 1, end + 1):
            m = _KEY_LINE_RE.match(lines[i])
            if not m:
                continue
            key = m.group(2)
            if key not in values:
                continue
            found.add(key)
            indent, _, sep, rest = m.groups()
            comment = ""
            if "#" in rest:
                rest, comment = rest.split("#", 1)
                comment = "#" + comment
            lines[i] = f"{indent}{key}{sep}{_value_to_toml(values[key])}" + (
                (" " + comment.strip()) if comment else ""
            )
        missing = [k for k in values if k not in found]
        if missing:
            # Insert after the last non-empty line of the section.
            insert_at = end
            for j in range(end, start, -1):
                if lines[j].strip():
                    insert_at = j
                    break
            for key in missing:
                insert_at += 1
                lines.insert(insert_at, f"{key} = {_value_to_toml(values[key])}")

    # Process the later section first so line indices of the earlier section
    # stay valid while inserting lines.
    edits = [
        ("params", updates.get("params") or {}, ALLOWED_HUGO_KEYS),
        ("params.contact", updates.get("contact") or {}, ALLOWED_HUGO_CONTACT_KEYS),
    ]
    positions = _section_ranges(lines)
    edits.sort(
        key=lambda item: positions.get(item[0], (10**9, 10**9))[0],
        reverse=True,
    )
    for section, values, allowed in edits:
        apply(section, values, allowed)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
