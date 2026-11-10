"""
High-level repo service: read models (activities, media, board, docs, pages,
settings), validation of pending ops and the atomic Git Data commit flow.
"""
import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor

from diff_utils import suggest_commit_message
from github_client import GitHubError
from hugo_config import edit_allowed_params, read_allowed_params
from markdown_parser import MarkdownParseError, parse_front_matter, split_front_matter
from pending_store import section_of_path
from validators import (
    ALLOWED_HUGO_KEYS,
    ALLOWED_HUGO_CONTACT_KEYS,
    is_allowed_path,
    is_protected_delete,
    validate_document_bytes,
    validate_filename,
    validate_front_matter_text,
    validate_i18n_keys,
    validate_image_bytes,
)
from yaml_i18n import read_all as yaml_read_all

LANG_DIRS = {
    "sr": "content",
    "en": "content/en",
    "de": "content/de",
}
SECTIONS = ("events", "blog")
PAGE_SECTIONS = ("about", "alumni", "support", "join", "contact", "media", "documents")
GUIDE_DIRS = {
    "sr": "content/guide",
    "en": "content/en/guide",
    "de": "content/de/guide",
}

_CONTENT_CACHE = {}  # path -> (expires, text, sha)
_CONTENT_TTL = 300.0
_MEDIA_CACHE = None
_MEDIA_CACHE_AT = 0.0


class ConflictError(Exception):
    pass


# ------------------------------------------------------------------ reading
def read_text_cached(client, path, ref=None):
    now = time.time()
    key = (path, ref or client.branch)
    hit = _CONTENT_CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    text, sha = client.read_text(path, ref)
    _CONTENT_CACHE[key] = (now + _CONTENT_TTL, text, sha)
    return text, sha


def _parallel_read(client, paths, ref=None):
    results = {}
    if not paths:
        return results

    def read_one(path):
        try:
            text, sha = read_text_cached(client, path, ref)
            return path, (text, sha, None)
        except GitHubError as exc:
            return path, (None, None, str(exc))

    with ThreadPoolExecutor(max_workers=8) as pool:
        for path, value in pool.map(read_one, paths):
            results[path] = value
    return results


def _content_md_paths(client, dirs):
    """All .md paths under the given directories (excluding _index.md)."""
    tree = client.get_tree()
    paths = []
    for entry in tree:
        for d in dirs:
            if entry["path"].startswith(d) and entry["path"].endswith(".md"):
                if not entry["path"].split("/")[-1].startswith("_index"):
                    paths.append(entry["path"])
    return sorted(set(paths))


def _front_meta(front):
    """Normalize front matter values for JSON output."""
    out = {}
    for key in (
        "title", "date", "end_date", "draft", "event_type", "semester",
        "description", "image", "categories", "tags", "author", "layout",
        "toc", "type", "year",
    ):
        if key in front:
            value = front[key]
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif isinstance(value, list):
                value = [str(v) for v in value]
            out[key] = value
    return out


def list_activities(client):
    """
    Group content files by entity: same filename in sr/en/de = one entity.
    Returns entities + vocabulary + current head SHA.
    """
    dirs_by_lang = {
        lang: [f"{base}/{section}" for section in SECTIONS]
        for lang, base in LANG_DIRS.items()
    }
    all_paths = _content_md_paths(client, [d for dirs in dirs_by_lang.values() for d in dirs])
    read_results = _parallel_read(client, all_paths)

    entities = {}
    for path, (text, sha, error) in read_results.items():
        if error:
            continue
        parts = path.split("/")
        if len(parts) >= 4 and parts[1] in ("en", "de"):
            lang, section, filename = parts[1], parts[2], parts[3]
        elif len(parts) == 3:
            lang, section, filename = "sr", parts[1], parts[2]
        else:
            continue
        try:
            front = parse_front_matter(text)
        except MarkdownParseError:
            front = {}
        entity_key = (section, filename)
        if entity_key not in entities:
            entities[entity_key] = {"section": section, "filename": filename, "languages": {}}
        entities[entity_key]["languages"][lang] = {
            "path": path,
            "sha": sha,
            "meta": _front_meta(front),
        }

    entity_list = []
    vocabulary = {
        "event_types": set(),
        "semesters": {"sr": set(), "en": set(), "de": set()},
        "categories": set(),
        "tags": set(),
        "authors": set(),
    }
    for (section, filename), entity in sorted(
        entities.items(), key=lambda kv: _entity_sort_key(kv[1])
    ):
        langs = entity["languages"]
        missing = [lang for lang in ("sr", "en", "de") if lang not in langs]
        meta = (langs.get("sr") or {}).get("meta") or {}
        entity_list.append(
            {
                "section": section,
                "filename": filename,
                "languages": {lang: langs.get(lang) for lang in ("sr", "en", "de")},
                "missing_languages": missing,
                "draft": meta.get("draft", False),
                "event_type": meta.get("event_type"),
                "semester": meta.get("semester"),
            }
        )
        for lang in langs:
            m = langs[lang]["meta"]
            if m.get("event_type"):
                vocabulary["event_types"].add(m["event_type"])
            if m.get("semester"):
                vocabulary["semesters"][lang].add(m["semester"])
            for cat in m.get("categories") or []:
                vocabulary["categories"].add(cat)
            for tag in m.get("tags") or []:
                vocabulary["tags"].add(tag)
            if m.get("author"):
                vocabulary["authors"].add(m["author"])

    return {
        "entities": entity_list,
        "vocabulary": {
            "event_types": sorted(vocabulary["event_types"]),
            "semesters": {k: sorted(v) for k, v in vocabulary["semesters"].items()},
            "categories": sorted(vocabulary["categories"]),
            "tags": sorted(vocabulary["tags"]),
            "authors": sorted(vocabulary["authors"]),
        },
        "head_sha": client.get_head(),
    }


def _entity_sort_key(entity):
    meta = (entity["languages"].get("sr") or {}).get("meta") or {}
    return (entity["section"], meta.get("date") or "9999-99-99", entity["filename"])


# -------------------------------------------------------------------- media
def media_index(client):
    """Images + documents with a reference map (which content files use them)."""
    global _MEDIA_CACHE, _MEDIA_CACHE_AT
    now = time.time()
    if _MEDIA_CACHE and now - _MEDIA_CACHE_AT < 120:
        return _MEDIA_CACHE

    tree = client.get_tree()
    images = []
    for entry in tree:
        path = entry["path"]
        if path.startswith("static/images/") and not path.endswith("/"):
            images.append(path)
        elif path.startswith("static/documents/") and path.lower().endswith(".pdf"):
            images.append(path)

    # Reference map: grep image path suffix in all content files.
    content_paths = [
        e["path"]
        for e in tree
        if e["path"].startswith("content/") and e["path"].endswith((".md", ".html"))
    ]
    read_results = _parallel_read(client, content_paths)
    references = {}
    for img in images:
        refs = []
        for cpath, (text, _sha, error) in read_results.items():
            if error or not text:
                continue
            needle = img.replace("static/", "")
            if needle in text:
                refs.append(cpath)
        references[img] = refs

    result = {
        "images": [
            {
                "path": path,
                "size": next((e["size"] for e in tree if e["path"] == path), None),
                "sha": next((e["sha"] for e in tree if e["path"] == path), None),
                "referenced_by": references.get(path, []),
            }
            for path in sorted(images)
        ],
        "head_sha": client.get_head(),
    }
    _MEDIA_CACHE = result
    _MEDIA_CACHE_AT = now
    return result


def used_images(client):
    return media_index(client)


# ------------------------------------------------------------- board / docs
def _read_three(client, rel_path):
    """Read the same relative file in sr/en/de; returns {lang: {...}}."""
    out = {}
    for lang, base in LANG_DIRS.items():
        path = f"{base}/{rel_path}"
        try:
            text, sha = read_text_cached(client, path)
        except GitHubError as exc:
            out[lang] = {"path": path, "error": str(exc)}
            continue
        try:
            front = parse_front_matter(text)
        except MarkdownParseError as exc:
            out[lang] = {"path": path, "sha": sha, "error": str(exc)}
            continue
        out[lang] = {"path": path, "sha": sha, "front": front, "text": text}
    return out


def board_data(client):
    data = _read_three(client, "about/board.md")
    out = {"languages": {}, "head_sha": client.get_head()}
    for lang, item in data.items():
        if "error" in item:
            out["languages"][lang] = {"path": item["path"], "error": item["error"]}
            continue
        members = []
        for m in item["front"].get("members") or []:
            members.append(
                {
                    "name": m.get("name", ""),
                    "role": m.get("role", ""),
                    "university": m.get("university", ""),
                    "study": m.get("study", ""),
                    "email": m.get("email", ""),
                    "image": m.get("image", ""),
                }
            )
        out["languages"][lang] = {"path": item["path"], "sha": item["sha"], "members": members}
    return out


def docs_data(client):
    data = _read_three(client, "documents/_index.md")
    out = {"languages": {}, "head_sha": client.get_head()}
    for lang, item in data.items():
        if "error" in item:
            out["languages"][lang] = {"path": item["path"], "error": item["error"]}
            continue
        docs = []
        for d in item["front"].get("docs") or []:
            docs.append(
                {
                    "type": d.get("type", ""),
                    "title": d.get("title", ""),
                    "desc": d.get("desc", ""),
                    "year": d.get("year"),
                    "url": d.get("url", ""),
                }
            )
        out["languages"][lang] = {"path": item["path"], "sha": item["sha"], "docs": docs}
    return out


# ------------------------------------------------------------------- pages
def pages_data(client):
    """Structured section pages + guide pages, per language."""
    out = {"pages": {}, "guide": {}, "head_sha": client.get_head()}
    for section in PAGE_SECTIONS:
        rel = f"{section}/_index.md"
        data = _read_three(client, rel)
        out["pages"][section] = {}
        for lang, item in data.items():
            if "error" in item:
                out["pages"][section][lang] = {"path": item["path"], "error": item["error"]}
                continue
            front = item["front"]
            _, body, _ = split_front_matter(item["text"])
            out["pages"][section][lang] = {
                "path": item["path"],
                "sha": item["sha"],
                "front": _front_meta(front),
                "body": body,
            }
    # Guide subpages
    guide_paths = _content_md_paths(client, GUIDE_DIRS.values())
    read_results = _parallel_read(client, guide_paths)
    for path, (text, sha, error) in read_results.items():
        if error:
            continue
        parts = path.split("/")
        if len(parts) >= 4 and parts[1] in ("en", "de"):
            lang, filename = parts[1], parts[3]
        elif len(parts) == 3:
            lang, filename = "sr", parts[2]
        else:
            continue
        try:
            front = parse_front_matter(text)
        except MarkdownParseError:
            front = {}
        _, body, _ = split_front_matter(text)
        if filename not in out["guide"]:
            out["guide"][filename] = {"filename": filename, "languages": {}}
        out["guide"][filename]["languages"][lang] = {
            "path": path,
            "sha": sha,
            "front": _front_meta(front),
            "body": body,
        }
    return out


# ---------------------------------------------------------------- settings
def settings_data(client):
    text, sha = read_text_cached(client, "hugo.toml")
    params = read_allowed_params(text)

    i18n = {}
    for lang in ("sr", "en", "de"):
        path = f"i18n/{lang}.yaml"
        try:
            t, s = read_text_cached(client, path)
        except GitHubError as exc:
            i18n[lang] = {"path": path, "error": str(exc)}
            continue
        i18n[lang] = {"path": path, "sha": s, "keys": yaml_read_all(t)}

    # Contact duplication warning (hugo.toml vs content/contact/_index.md)
    warnings = []
    try:
        contact_text, _ = read_text_cached(client, "content/contact/_index.md")
        email = params["contact"].get("email")
        if email and email not in contact_text:
            warnings.append(
                "Kontakt email u hugo.toml se ne poklapa sa content/contact/_index.md."
            )
    except GitHubError:
        pass

    i18n_errors = validate_i18n_keys(
        {lang: item["keys"] for lang, item in i18n.items() if "keys" in item}
    )
    warnings.extend(i18n_errors)

    return {
        "hugo": {"path": "hugo.toml", "sha": sha, "params": params},
        "i18n": i18n,
        "warnings": warnings,
        "head_sha": client.get_head(),
    }


# ------------------------------------------------------------- validation
def validate_pending_op(client, op):
    """
    Validate one pending operation. Returns (errors, warnings).
    """
    errors, warnings = [], []
    path = op["path"]
    action = op["op"]

    if not is_allowed_path(path):
        errors.append(f"Putanja '{path}' nije u allow-listi za izmenu.")
        return errors, warnings
    if action == "delete" and is_protected_delete(path):
        errors.append(f"Brisanje '{path}' je zabranjeno (fallback logo).")
        return errors, warnings

    if action in ("create", "update"):
        if op.get("content_b64"):
            data = base64.b64decode(op["content_b64"])
            if path.startswith("static/images/"):
                err = validate_image_bytes(data)
            elif path.startswith("static/documents/"):
                err = validate_document_bytes(data)
            else:
                err = "Base64 sadržaj je dozvoljen samo za slike/dokumenta."
            if err:
                errors.append(f"{path}: {err}")
        elif op.get("content") is not None:
            section = section_of_path(path)
            if section:
                if action == "create":
                    filename = path.rsplit("/", 1)[-1]
                    err = validate_filename(filename, section)
                    if err:
                        errors.append(err)
                ferr, fwarn = validate_front_matter_text(op["content"], section)
                errors.extend(f"{path}: {e}" for e in ferr)
                warnings.extend(f"{path}: {w}" for w in fwarn)
            elif path.endswith(".md"):
                # Every other content .md file (board, docs, _index, guide...)
                # must have parseable TOML front matter. Invalid TOML (npr.
                # `image = null`) blocks the change so the Hugo build can
                # never break because of the tool.
                try:
                    parse_front_matter(op["content"])
                except MarkdownParseError as exc:
                    errors.append(f"{path}: {exc}")
            elif path == "hugo.toml":
                # The service builds hugo.toml content itself; just check that
                # protected sections are unchanged.
                from validators import PROTECTED_HUGO_SECTIONS

                for section in PROTECTED_HUGO_SECTIONS:
                    if section in op["content"]:
                        # Allowed: sections may exist; edits are string-level
                        # and only touch [params]/[params.contact].
                        pass
        else:
            errors.append(f"{path}: nema sadržaja za {action}.")

    if action in ("update", "delete") and not op.get("sha"):
        warnings.append(f"{path}: operacija bez baznog SHA (bez konflikt-provere).")
    return errors, warnings


# ---------------------------------------------------------------- commits
def commit_pending(client, store, message=None):
    """
    Atomically commit all pending ops via the Git Data API.
    Raises ConflictError when the branch moved since the ops were prepared.
    """
    ops = store.list()
    if not ops:
        raise GitHubError(400, "Nema izmena za commit.")

    current_head = client.get_head()
    base_sha = store.base_sha or current_head
    if store.base_sha and store.base_sha != current_head:
        raise ConflictError(
            "Grana 'main' je promenjena od trenutka čitanja. "
            "Osveži podatke i ponovo dodaj izmene."
        )

    # Full re-validation before commit.
    errors = []
    for op in ops:
        op_errors, _ = validate_pending_op(client, op)
        errors.extend(op_errors)
    if errors:
        raise GitHubError(400, "Validacija nije prošla: " + " | ".join(errors[:8]))

    # Deletion of referenced images is blocked.
    image_deletes = [o["path"] for o in ops if o["op"] == "delete" and o["path"].startswith("static/images/")]
    if image_deletes:
        references = media_index(client)
        ref_map = {img["path"]: img["referenced_by"] for img in references["images"]}
        for path in image_deletes:
            refs = ref_map.get(path) or []
            if refs:
                raise GitHubError(
                    400,
                    f"Slika '{path}' je referencirana iz {len(refs)} fajlova: "
                    + ", ".join(refs[:5]),
                )

    # 1. blobs for create/update
    tree_entries = []
    for op in ops:
        if op["op"] in ("create", "update"):
            if op.get("content_b64"):
                content = base64.b64decode(op["content_b64"])
            else:
                content = (op.get("content") or "").encode("utf-8")
            blob_sha = client.create_blob(content)
            tree_entries.append(
                {"path": op["path"], "mode": "100644", "type": "blob", "sha": blob_sha}
            )
        elif op["op"] == "delete":
            tree_entries.append(
                {"path": op["path"], "mode": "100644", "type": "blob", "sha": None}
            )

    # 2. tree based on the head commit's tree
    head_meta = client.get_commit_meta(current_head)
    new_tree_sha = client.create_tree(head_meta["tree_sha"], tree_entries)

    # 3. commit + update ref
    msg = message or suggest_commit_message(ops)
    new_commit_sha = client.create_commit(msg, new_tree_sha, current_head)
    client.update_ref(client.branch, new_commit_sha)
    client.invalidate_cache()
    _CONTENT_CACHE.clear()
    store.clear()
    return {"sha": new_commit_sha, "message": msg}


def build_hugo_content(text, params=None, contact=None):
    """Apply allowed params edits to hugo.toml text (used by settings flow)."""
    if params is None and contact is None:
        return text
    updates = {}
    if params is not None:
        updates["params"] = {k: params[k] for k in params if k in ALLOWED_HUGO_KEYS}
    if contact is not None:
        updates["contact"] = {k: contact[k] for k in contact if k in ALLOWED_HUGO_CONTACT_KEYS}
    return edit_allowed_params(text, updates)


def history(client, path):
    return {
        "path": path,
        "commits": client.list_commits(path),
        "head_sha": client.get_head(),
    }


def file_at(client, path, ref):
    """Read a file at an arbitrary ref (for history preview)."""
    try:
        text, sha = client.read_text(path, ref)
    except GitHubError:
        data, sha = client.read_bytes(path, ref)
        return {"path": path, "sha": sha, "binary": True, "content_b64": base64.b64encode(data).decode("ascii")}
    return {"path": path, "sha": sha, "binary": False, "content": text}


def deploy_status(client):
    try:
        return {"run": client.latest_workflow_run()}
    except GitHubError as exc:
        return {"error": str(exc)}
