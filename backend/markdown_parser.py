"""
Markdown file parser for Hugo content.

Front matter is TOML between `+++` markers:
    +++
    title = "..."
    date = 2026-09-25
    +++
    Markdown body...

Round-trip requirements:
- unknown front matter fields are preserved (dict order is kept),
- the body is returned untouched,
- serialization always produces valid TOML.
"""
import datetime
import json
import re

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover - Python < 3.11
    _toml = None  # type: ignore

FM_OPEN_RE = re.compile(r"^\s*\+\+\+\s*$")
FM_CLOSE_RE = re.compile(r"^\s*\+\+\+\s*$")


class MarkdownParseError(ValueError):
    pass


# ------------------------------------------------------------------- parsing
def split_front_matter(text):
    """
    Split a Hugo markdown file into (front_matter_text, body, error).
    If there is no front matter, front_matter_text is None and the whole
    text is the body.
    """
    if text is None:
        raise MarkdownParseError("Prazan fajl.")
    lines = text.splitlines()
    if not lines:
        return None, text, None
    first = lines[0]
    if not FM_OPEN_RE.match(first):
        return None, text, None
    close_idx = None
    for i in range(1, len(lines)):
        if FM_CLOSE_RE.match(lines[i]):
            close_idx = i
            break
    if close_idx is None:
        raise MarkdownParseError("Front matter nije zatvoren (nedostaje `+++`).")
    fm_text = "\n".join(lines[1:close_idx])
    body = "\n".join(lines[close_idx + 1 :])
    # Keep exactly one trailing newline after front matter on merge; body is
    # returned verbatim without leading blank lines.
    return fm_text, body.lstrip("\n"), None


def parse_toml(fm_text):
    """Parse TOML front matter into an ordered dict."""
    if not fm_text or not fm_text.strip():
        return {}
    if _toml is None:
        raise MarkdownParseError("TOML parsiranje nije dostupno (potreban Python 3.11+).")
    try:
        return _toml.loads(fm_text)
    except Exception as exc:
        raise MarkdownParseError(f"Neispravan TOML front matter: {exc}") from exc


def parse_front_matter(text):
    """Parse a markdown file; returns dict of front matter fields."""
    fm_text, _body, err = split_front_matter(text)
    if err:
        raise err
    if fm_text is None:
        return {}
    return parse_toml(fm_text)


# -------------------------------------------------------------- serialization
def _escape_basic_string(value):
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def serialize_toml_value(value):
    """Serialize a Python value (from tomllib) into TOML text.

    None is never valid TOML — it is serialized as an empty string so the
    tool can never produce a `null` that would break the Hugo build.
    """
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _escape_basic_string(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(serialize_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if not isinstance(k, str) or not re.match(r"^[A-Za-z0-9_-]+$", k):
                k = _escape_basic_string(str(k))
            parts.append(f"{k} = {serialize_toml_value(v)}")
        return "{ " + ", ".join(parts) + " }"
    # Last resort: JSON-ish fallback (should not happen for TOML types)
    return json.dumps(value)


def serialize_front_matter(data):
    """Serialize an ordered dict into a TOML document."""
    lines = []
    for key, value in data.items():
        if not isinstance(key, str) or not re.match(r"^[A-Za-z0-9_-]+$", key):
            key = _escape_basic_string(str(key))
        lines.append(f"{key} = {serialize_toml_value(value)}")
    return "\n".join(lines)


# ------------------------------------------------------------------- merging
def merge_front_matter(text, updates, remove=None):
    """
    Apply `updates` (dict) to the front matter of `text`, round-tripping all
    other fields. `remove` is a list of field names to delete. Returns new text.
    """
    fm_text, body, err = split_front_matter(text)
    if err:
        raise err
    data = parse_toml(fm_text) if fm_text is not None else {}
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    for key in remove or []:
        data.pop(key, None)
    new_fm = serialize_front_matter(data)
    body = (body or "").rstrip("\n")
    if body:
        return "+++\n" + new_fm + "\n+++\n\n" + body + "\n"
    return "+++\n" + new_fm + "\n+++\n"


def build_markdown(front_data, body=""):
    """Build a markdown file from a front matter dict and a body."""
    return (
        "+++\n"
        + serialize_front_matter(front_data)
        + "\n+++\n\n"
        + (body or "").rstrip("\n")
        + "\n"
    )
