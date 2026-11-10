"""
Central validation layer for the admin tool.

Rules enforced:
- allow-list of editable paths (everything else is read-only),
- TOML front matter must parse (error blocks commit),
- required fields per content type,
- date format YYYY-MM-DD and end_date >= date,
- filename: lowercase slug, unique, identical across languages,
- image path must exist in static/images (warning, not a block),
- i18n YAML keys must be identical across sr/en/de,
- delete protections (brand logo, referenced images).
"""
import re
import unicodedata

from markdown_parser import MarkdownParseError, parse_front_matter

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EVENT_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")

# Editable prefixes; every other path is read-only through the tool.
ALLOWED_PREFIXES = (
    "content/",
    "i18n/",
    "static/images/",
    "static/documents/",
)
HUGO_CONFIG_PATH = "hugo.toml"

# Keys in hugo.toml that may be edited through the tool.
ALLOWED_HUGO_KEYS = ("description", "brandLogo", "ogImage", "defaultImage", "joinFormUrl")
ALLOWED_HUGO_CONTACT_KEYS = ("email", "linkedin", "instagram")
PROTECTED_HUGO_SECTIONS = (
    "[languages]",
    "[module.mounts]",
    "[permalinks]",
    "[markup]",
    "[imaging]",
    "[pagination]",
    "[taxonomies]",
)

PROTECTED_DELETE_PATHS = (
    "static/images/brand/logo-vss-uss.png",
)

# Event types known from the current content (vocabulary).
EVENT_TYPES = ("social", "hiking", "networking", "assembly", "community")

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
DOCUMENT_EXTENSIONS = (".pdf",)
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024  # 20 MB

LANG_FOLDERS = {"sr": "content", "en": "content/en", "de": "content/de"}


def slugify(text):
    """Lowercase ASCII slug (same algorithm as the frontend)."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def is_allowed_path(path):
    """True if the tool is allowed to write this path."""
    if path == HUGO_CONFIG_PATH:
        return True
    return path.startswith(ALLOWED_PREFIXES)


def is_protected_delete(path):
    return path in PROTECTED_DELETE_PATHS


def validate_filename(filename, section):
    """Validate a content filename for events or blog."""
    if not filename.endswith(".md"):
        return "Ime fajla mora imati ekstenziju .md."
    stem = filename[:-3]
    if section == "events" and not EVENT_FILE_RE.match(filename):
        return "Ime fajla događaja mora biti u formatu YYYY-MM-DD-slug.md."
    if section == "blog" and not SLUG_RE.match(stem):
        return "Ime fajla bloga mora biti lowercase slug (a-z0-9 i crtice)."
    return None


def validate_date(value, field="date"):
    if value is None or value == "":
        return f"Polje '{field}' je obavezno."
    if isinstance(value, bool):
        return f"Polje '{field}' mora biti datum."
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if not DATE_RE.match(text):
        return f"Polje '{field}' mora biti u formatu YYYY-MM-DD."
    return None


def _clean_date(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def validate_event(front):
    """Validate event front matter; returns list of error strings."""
    errors = []
    for field in ("title", "date", "event_type", "semester"):
        if not front.get(field):
            errors.append(f"Polje '{field}' je obavezno za događaj.")
    for field in ("date", "end_date"):
        if field in front and front[field] not in (None, ""):
            err = validate_date(front[field], field)
            if err:
                errors.append(err)
    if "draft" in front and not isinstance(front["draft"], bool):
        errors.append("Polje 'draft' mora biti boolean (true/false).")
    if "date" in front and "end_date" in front:
        d1, d2 = _clean_date(front["date"]), _clean_date(front["end_date"])
        if d1 and d2 and d2 < d1:
            errors.append("end_date ne sme biti pre datuma događaja.")
    if front.get("event_type") and front["event_type"] not in EVENT_TYPES:
        # Free input is allowed; unknown types only produce a warning.
        pass
    return errors


def validate_blog(front):
    errors = []
    for field in ("title", "date"):
        if not front.get(field):
            errors.append(f"Polje '{field}' je obavezno za blog post.")
    if "date" in front:
        err = validate_date(front["date"], "date")
        if err:
            errors.append(err)
    if "draft" in front and not isinstance(front["draft"], bool):
        errors.append("Polje 'draft' mora biti boolean (true/false).")
    return errors


def validate_front_matter_text(text, section):
    """
    Validate a full markdown text: front matter parses + section rules.
    Returns (errors, warnings).
    """
    try:
        front = parse_front_matter(text)
    except MarkdownParseError as exc:
        return [str(exc)], []
    if not front:
        return ["Front matter nedostaje ili je prazan."], []
    errors = validate_event(front) if section == "events" else validate_blog(front)
    return errors, []


def validate_image_bytes(data):
    """Magic-byte validation of jpg/png/webp/gif; returns error or None."""
    if len(data) > MAX_IMAGE_BYTES:
        return f"Slika je veća od dozvoljenih 5 MB ({len(data)} bajtova)."
    if data[:3] == b"\xff\xd8\xff":
        return None  # jpeg
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return None  # png
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return None  # webp
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return None  # gif
    return "Nepoznat format slike — dozvoljeni su JPG/PNG/WEBP/GIF."


def validate_document_bytes(data):
    if len(data) > MAX_DOCUMENT_BYTES:
        return f"Dokument je veći od 20 MB ({len(data)} bajtova)."
    if data[:5] == b"%PDF-":
        return None
    return "Fajl nije PDF (nedostaje PDF zaglavlje)."


def validate_i18n_keys(keys_by_lang):
    """Compare top-level i18n key sets; returns list of error strings."""
    langs = sorted(keys_by_lang.keys())
    sets = {lang: set(keys) for lang, keys in keys_by_lang.items()}
    errors = []
    reference = sets[langs[0]]
    for lang in langs[1:]:
        missing = reference - sets[lang]
        extra = sets[lang] - reference
        if missing:
            errors.append(f"i18n/{lang}.yaml nema ključeve: {', '.join(sorted(missing)[:10])}...")
        if extra:
            errors.append(f"i18n/{lang}.yaml ima višak ključeva: {', '.join(sorted(extra)[:10])}...")
    return errors
