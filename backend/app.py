"""
Admin tool backend (Flask).

Legacy endpoints (unchanged behaviour):
    POST /login    admin login (returns a session token)
    POST /save     push a new activity (single md + optional PNG image)

New API endpoints (all changes go through the pending store, then commit):
    GET  /api/tree            cached recursive listing
    GET  /api/file            read a file (optionally at a ref)
    GET  /api/activities      events + blog grouped by entity (3 languages)
    GET  /api/media           images + documents + reference map
    GET  /api/board           board members per language
    GET  /api/docs            documents per language
    GET  /api/pages           structured pages + guide pages
    GET  /api/settings        hugo.toml editable params + i18n keys + warnings
    GET  /api/history         commit history for a path
    GET  /api/deploy          latest workflow run status
    POST /api/translate       sr -> en/de machine translation
    GET/POST/DELETE /api/pending     pending changes with diffs
    POST /api/pending/activity       create/update activity files
    POST /api/pending/activity-delete  soft (draft) / hard delete
    POST /api/pending/activity-rename
    POST /api/pending/board          board members (3 languages)
    POST /api/pending/docs           documents (3 languages)
    POST /api/pending/page           structured page editor
    POST /api/pending/settings       hugo.toml allowed params
    POST /api/pending/i18n           i18n key values
    POST /api/commit         atomic Git Data commit of pending changes
"""
import base64
import hmac
import mimetypes
import os
import secrets
import time

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

import repo_service
import translation
import validators
from diff_utils import line_diff, suggest_commit_message
from github_client import GitHubClient, GitHubError, raw_url
from markdown_parser import build_markdown, merge_front_matter
from pending_store import get_store
from repo_service import ConflictError, read_text_cached
from yaml_i18n import set_values as yaml_set_values

load_dotenv()
app = Flask(__name__)


def _allowed_origins():
    """Comma-separated ALLOWED_ORIGINS; defaults to the local dev frontend."""
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:3000", "http://127.0.0.1:3000"]


CORS(app, origins=_allowed_origins())

# ----------------------------------------------------------------- config
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_OWNER = os.environ.get("REPO_OWNER")
REPO_NAME = os.environ.get("REPO_NAME")
BRANCH = os.environ.get("BRANCH", "main")
FOLDER_PATH = os.environ.get("FOLDER_PATH", "content/posts")  # legacy
ADMIN_USER = os.environ.get("ADMIN_USER")
ADMIN_PASS = os.environ.get("ADMIN_PASS")

# Built React app (frontend/build) is served by this Flask process when
# present — this makes `python app.py` a full single-process deployment.
FRONTEND_BUILD = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "build")
)

LOCAL_SAVE_DIR = "content/posts"  # legacy local mirror
IMAGES_DIR = "images/blogs"  # legacy local mirror
os.makedirs(LOCAL_SAVE_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

_SESSION_TTL = float(os.environ.get("SESSION_TTL_HOURS", "12")) * 3600
_SESSIONS = {}  # in-memory session token -> expiry timestamp

_LOGIN_WINDOW = 300.0
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_ATTEMPTS = {}  # client ip -> recent failed-attempt timestamps

_IMAGE_CACHE = {}  # path -> (expires, bytes)
_IMAGE_TTL = 300.0
_IMAGE_CACHE_MAX_ENTRIES = 200


def get_client():
    return GitHubClient(GITHUB_TOKEN, REPO_OWNER, REPO_NAME, BRANCH)


def _authorized():
    """API auth: session token, only when admin credentials are configured."""
    if not ADMIN_USER or not ADMIN_PASS:
        return False  # fail closed: unconfigured credentials never authorize
    token = request.headers.get("X-Admin-Token") or request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ").strip()
    if not token:
        return False
    expiry = _SESSIONS.get(token)
    if not expiry:
        return False
    if expiry < time.time():
        _SESSIONS.pop(token, None)
        return False
    return True


def _require_auth():
    if not _authorized():
        return jsonify({"error": "Nedostaje administratorska sesija."}), 401
    return None


def _login_throttled(client_ip):
    """True when this client burned through its failed-login budget."""
    now = time.time()
    for ip, stamps in list(_LOGIN_ATTEMPTS.items()):
        recent = [t for t in stamps if now - t < _LOGIN_WINDOW]
        if recent:
            _LOGIN_ATTEMPTS[ip] = recent
        else:
            _LOGIN_ATTEMPTS.pop(ip, None)
    return len(_LOGIN_ATTEMPTS.get(client_ip, ())) >= _LOGIN_MAX_ATTEMPTS


def _serve_frontend(path=""):
    """Serve the built React app (SPA fallback) or a helpful status page."""
    path = (path or "").lstrip("/")
    if os.path.isdir(FRONTEND_BUILD):
        if path:
            build_root = os.path.realpath(FRONTEND_BUILD)
            target = os.path.realpath(
                os.path.join(build_root, path.replace("/", os.sep))
            )
            if target.startswith(build_root + os.sep) and os.path.isfile(target):
                return send_from_directory(FRONTEND_BUILD, path)
            if path == "favicon.ico":
                return "", 204
        index = os.path.join(FRONTEND_BUILD, "index.html")
        if os.path.isfile(index):
            return send_from_directory(FRONTEND_BUILD, "index.html")
    if path == "favicon.ico":
        return "", 204
    return (
        "<!doctype html><html><body style='font-family:sans-serif;background:#1e1e2f;"
        "color:#f0f0f0;display:flex;align-items:center;justify-content:center;"
        "min-height:100vh;margin:0'>"
        "<div><h2>VSS Admin — backend radi ✓</h2>"
        "<p>Frontend nije pronađen u <code>frontend/build</code>.</p>"
        "<p>Pokreni <code>npm run build</code> u frontend/ (pa restartuj backend) ili "
        "<code>npm start</code> i otvori http://localhost:3000.</p></div></body></html>"
    )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa_fallback(path):
    """Root + SPA routes; API typos still return JSON 404."""
    if path.startswith("api/"):
        return jsonify({"error": "Nepoznata API ruta."}), 404
    return _serve_frontend(path)


@app.errorhandler(GitHubError)
def handle_github_error(exc):
    status = exc.status if exc.status in (400, 401, 403, 404, 409) else 502
    return jsonify({"error": exc.message, "status": exc.status}), status


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    """404/405... stay as-is (JSON for API, SPA fallback for browser paths)."""
    if request.path.startswith("/api/"):
        return jsonify({"error": exc.description}), exc.code
    if exc.code == 404:
        return _serve_frontend(request.path)
    return jsonify({"error": exc.description}), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Full detail stays in the server log; the client gets no internals.
    app.logger.exception("Unexpected error")
    return jsonify({"error": "Interna greška na serveru."}), 500


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if response.mimetype == "text/html":
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
            "font-src 'self' data:; connect-src 'self' https:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'self'",
        )
    return response


# ---------------------------------------------------------------- legacy
def github_put_file(path, content, commit_message_str, is_binary=False):
    """Legacy helper kept for /save compatibility (Contents API)."""
    client = get_client()
    try:
        meta = client.get_contents_meta(path)
        sha = meta.get("sha")
    except GitHubError:
        sha = None
    if is_binary:
        payload = content
    else:
        payload = content.encode("utf-8")
    client.put_contents(path, payload, commit_message_str, sha)
    return True, ""


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "")
    password = str(data.get("password") or "")
    client_ip = request.remote_addr or "?"
    if _login_throttled(client_ip):
        return (
            jsonify(
                {"success": False, "error": "Previše pokušaja prijave — pokušaj kasnije."}
            ),
            429,
        )
    if not ADMIN_USER or not ADMIN_PASS:
        return (
            jsonify({"success": False, "error": "Admin kredencijali nisu konfigurisani."}),
            503,
        )
    user_ok = hmac.compare_digest(username.encode(), ADMIN_USER.encode())
    pass_ok = hmac.compare_digest(password.encode(), ADMIN_PASS.encode())
    if user_ok and pass_ok:
        _LOGIN_ATTEMPTS.pop(client_ip, None)
        now = time.time()
        for old_token, expiry in list(_SESSIONS.items()):
            if expiry < now:
                _SESSIONS.pop(old_token, None)
        token = secrets.token_hex(32)
        _SESSIONS[token] = now + _SESSION_TTL
        return (
            jsonify({"success": True, "token": token, "expires_in": int(_SESSION_TTL)}),
            200,
        )
    _LOGIN_ATTEMPTS.setdefault(client_ip, []).append(time.time())
    return jsonify({"success": False, "error": "Pogrešni podaci"}), 401


def _local_path(base_dir, name):
    """Resolve a path inside base_dir; anything escaping it is rejected."""
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(target) != base:
        raise ValueError("Neispravna putanja.")
    return target


@app.route("/save", methods=["POST"])
def save_post():
    """
    Legacy flow (preserved): saves a markdown post + optional PNG image.
    """
    auth = _require_auth()
    if auth:
        return auth
    try:
        data = request.get_json(silent=True) or {}
        slug = data.get("slug")
        front = data.get("front")
        content = data.get("content")
        image_base64 = data.get("image")

        if not slug or not front or not content:
            return jsonify({"error": "Missing data"}), 400
        if not isinstance(slug, str) or not validators.SLUG_RE.match(slug):
            return (
                jsonify({"error": "Neispravan slug (dozvoljeni su a-z, 0-9 i crtice)."}),
                400,
            )
        if not isinstance(front, str) or not isinstance(content, str):
            return jsonify({"error": "Neispravan format podataka."}), 400

        if image_base64:
            if not isinstance(image_base64, str) or not image_base64.startswith(
                "data:image/png;base64,"
            ):
                return jsonify({"error": "Only PNG images are allowed"}), 400
            header, encoded = image_base64.split(",", 1)
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except ValueError:
                return jsonify({"error": "Neispravna base64 slika."}), 400
            if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                return jsonify({"error": "Only PNG images are allowed"}), 400
            if len(image_bytes) > validators.MAX_IMAGE_BYTES:
                return jsonify({"error": "Slika je prevelika (max 5 MB)."}), 400

            local_image_path = _local_path(IMAGES_DIR, f"{slug}.png")
            with open(local_image_path, "wb") as f:
                f.write(image_bytes)

            github_image_path = f"static/images/blogs/{slug}.png"
            try:
                github_put_file(
                    github_image_path,
                    image_bytes,
                    f"Add image {slug}",
                    is_binary=True,
                )
            except GitHubError as exc:
                return jsonify(
                    {
                        "error": "Failed to upload image to GitHub",
                        "github_response": exc.message,
                    }
                ), 500
            _IMAGE_CACHE.pop(github_image_path, None)

        image_field = (
            f'image: "/images/blogs/{slug}.png"' if image_base64 else 'image: ""'
        )
        front_lines = front.splitlines()
        front_lines = [line for line in front_lines if not line.startswith("image:")]
        for i, line in enumerate(front_lines):
            if line.strip() == "---" and i != 0:
                front_lines.insert(i, image_field)
                break
        front_with_image = "\n".join(front_lines)

        full_content = front_with_image + "\n\n" + content

        local_md_path = _local_path(LOCAL_SAVE_DIR, f"{slug}.md")
        with open(local_md_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        github_md_path = f"{FOLDER_PATH}/{slug}.md"
        try:
            github_put_file(github_md_path, full_content, f"Add/Update post {slug}")
        except GitHubError as exc:
            return jsonify(
                {
                    "error": "Failed to upload markdown to GitHub",
                    "github_response": exc.message,
                }
            ), 500

        return jsonify({"status": "ok", "message": "Post and image uploaded successfully"}), 200

    except Exception:  # noqa: BLE001
        app.logger.exception("save failed")
        return jsonify({"error": "Interna greška na serveru."}), 500


# ---------------------------------------------------------------- reads
def _kind_of(path):
    if path.endswith((".md", ".markdown")):
        return "markdown"
    if path.endswith((".yaml", ".yml")):
        return "yaml"
    if path.endswith(".toml"):
        return "toml"
    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    if path.lower().endswith(".pdf"):
        return "document"
    return "other"


@app.route("/api/tree", methods=["GET"])
def api_tree():
    auth = _require_auth()
    if auth:
        return auth
    tree = get_client().get_tree()
    return jsonify(
        {
            "entries": [
                {
                    "path": e["path"],
                    "sha": e["sha"],
                    "size": e.get("size"),
                    "kind": _kind_of(e["path"]),
                }
                for e in tree
            ]
        }
    )


@app.route("/api/file", methods=["GET"])
def api_file():
    auth = _require_auth()
    if auth:
        return auth
    path = request.args.get("path")
    ref = request.args.get("ref")
    if not path:
        return jsonify({"error": "Nedostaje 'path'."}), 400
    try:
        return jsonify(repo_service.file_at(get_client(), path, ref))
    except GitHubError as exc:
        return jsonify({"error": exc.message}), exc.status if exc.status in (400, 401, 403, 404, 409) else 502


@app.route("/api/activities", methods=["GET"])
def api_activities():
    auth = _require_auth()
    if auth:
        return auth
    return jsonify(repo_service.list_activities(get_client()))


@app.route("/api/media", methods=["GET"])
def api_media():
    auth = _require_auth()
    if auth:
        return auth
    client = get_client()
    data = repo_service.media_index(client)
    data["raw_base"] = raw_url(REPO_OWNER, REPO_NAME, BRANCH, "")
    return jsonify(data)


@app.route("/api/board", methods=["GET"])
def api_board():
    auth = _require_auth()
    if auth:
        return auth
    return jsonify(repo_service.board_data(get_client()))


@app.route("/api/docs", methods=["GET"])
def api_docs():
    auth = _require_auth()
    if auth:
        return auth
    return jsonify(repo_service.docs_data(get_client()))


@app.route("/api/pages", methods=["GET"])
def api_pages():
    auth = _require_auth()
    if auth:
        return auth
    return jsonify(repo_service.pages_data(get_client()))


@app.route("/api/settings", methods=["GET"])
def api_settings():
    auth = _require_auth()
    if auth:
        return auth
    return jsonify(repo_service.settings_data(get_client()))


@app.route("/api/history", methods=["GET"])
def api_history():
    auth = _require_auth()
    if auth:
        return auth
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "Nedostaje 'path'."}), 400
    return jsonify(repo_service.history(get_client(), path))


@app.route("/api/deploy", methods=["GET"])
def api_deploy():
    auth = _require_auth()
    if auth:
        return auth
    return jsonify(repo_service.deploy_status(get_client()))


@app.route("/api/image", methods=["GET"])
def api_image():
    """
    Serve repo images/PDFs through the backend. Works for private repos too
    (raw.githubusercontent.com does not) and keeps the GitHub token off the
    client. Intentionally session-less: <img> tags cannot send auth headers.
    Only static/images/** and static/documents/** are served, read-only.
    """
    path = request.args.get("path") or ""
    segments = path.replace("\\", "/").split("/")
    if any(seg in ("", ".", "..") for seg in segments) or not (
        path.startswith("static/images/") or path.startswith("static/documents/")
    ):
        return jsonify({"error": "Nedozvoljena putanja."}), 400
    if not path.lower().endswith(
        validators.IMAGE_EXTENSIONS + validators.DOCUMENT_EXTENSIONS
    ):
        return jsonify({"error": "Nedozvoljen tip fajla."}), 400
    now = time.time()
    hit = _IMAGE_CACHE.get(path)
    if hit and hit[0] > now:
        data = hit[1]
    else:
        try:
            data, _ = get_client().read_bytes(path)
        except GitHubError as exc:
            status = exc.status if exc.status in (400, 401, 403, 404, 409) else 502
            return jsonify({"error": exc.message}), status
        if len(data) > 15 * 1024 * 1024:
            return jsonify({"error": "Fajl prevelik za prikaz."}), 400
        if len(_IMAGE_CACHE) >= _IMAGE_CACHE_MAX_ENTRIES:
            _IMAGE_CACHE.clear()
        _IMAGE_CACHE[path] = (now + _IMAGE_TTL, data)
    mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(data, mimetype=mimetype, headers={"Cache-Control": "private, max-age=300"})


@app.route("/api/translate", methods=["POST"])
def api_translate():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    texts = data.get("texts") or []
    target = data.get("target")
    if target not in ("en", "de"):
        return jsonify({"error": "Dozvoljeni target jezici: en, de."}), 400
    if not texts:
        return jsonify({"translations": []})
    try:
        provider = translation.get_provider()
        result = provider.translate(texts, target)
        return jsonify({"translations": result, "provider": provider.name})
    except translation.TranslationError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/activity", methods=["GET"])
def api_activity_detail():
    auth = _require_auth()
    if auth:
        return auth
    section = request.args.get("section")
    filename = request.args.get("filename")
    if section not in ("events", "blog") or not filename:
        return jsonify({"error": "Nedostaje section/filename."}), 400
    client = get_client()
    from markdown_parser import parse_front_matter, split_front_matter

    languages = {}
    for lang, lang_dir in validators.LANG_FOLDERS.items():
        path = f"{lang_dir}/{section}/{filename}"
        try:
            text, sha = read_text_cached(client, path)
        except GitHubError:
            continue
        fm, body, err = split_front_matter(text)
        if err:
            continue
        try:
            front = parse_front_matter(fm) if fm is not None else {}
        except Exception:
            front = {}
        languages[lang] = {"path": path, "sha": sha, "front": front, "body": body or ""}
    if not languages:
        return jsonify({"error": "Aktivnost ne postoji."}), 404
    return jsonify({"languages": languages, "head_sha": client.get_head()})


# ------------------------------------------------------------- pending
@app.route("/api/pending", methods=["GET", "POST", "DELETE"])
def api_pending():
    auth = _require_auth()
    if auth:
        return auth
    store = get_store()
    client = get_client()

    if request.method == "DELETE":
        op_id = request.args.get("op")
        if op_id:
            store.remove(op_id)
        else:
            store.clear()
        return jsonify({"status": "ok"})

    if request.method == "GET":
        ops = []
        for op in store.list():
            rendered = dict(op)
            rendered["diff"] = None
            rendered["prev"] = None
            rendered["binary"] = False
            if op.get("content_b64"):
                rendered["binary"] = True
                rendered["size"] = len(base64.b64decode(op["content_b64"]))
            elif op.get("content") is not None:
                prev = None
                if op["op"] in ("update", "delete"):
                    try:
                        prev, _ = read_text_cached(client, op["path"])
                    except GitHubError:
                        prev = None
                rendered["prev"] = prev
                rendered["diff"] = line_diff(prev or "", op["content"] or "")
            ops.append(rendered)
        return jsonify(
            {
                "ops": ops,
                "commit_message": suggest_commit_message(store.list()),
                "base_sha": store.base_sha,
            }
        )

    # POST: add raw ops (media uploads/replacements/deletes).
    data = request.get_json(silent=True) or {}
    ops = data.get("ops") or []
    if not ops:
        return jsonify({"error": "Nema operacija."}), 400
    errors = []
    for op in ops:
        op_errors, _ = repo_service.validate_pending_op(client, op)
        errors.extend(op_errors)
    if errors:
        return jsonify({"errors": errors}), 400
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify(
        {
            "status": "ok",
            "count": len(store.list()),
            "commit_message": suggest_commit_message(store.list()),
        }
    )


@app.route("/api/pending/activity", methods=["POST"])
def api_pending_activity():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    section = data.get("section")  # events | blog
    filename = data.get("filename")
    languages = data.get("languages") or {}
    if section not in ("events", "blog") or not filename:
        return jsonify({"error": "Nedostaje section/filename."}), 400

    client = get_client()
    store = get_store()
    tree_paths = {e["path"] for e in client.get_tree()}
    existing_shas = {}
    for lang, lang_dir in validators.LANG_FOLDERS.items():
        path = f"{lang_dir}/{section}/{filename}"
        if path in tree_paths:
            try:
                _, sha = read_text_cached(client, path)
                existing_shas[lang] = sha
            except GitHubError:
                existing_shas[lang] = None

    errors = []
    ops = []
    for lang in ("sr", "en", "de"):
        payload = languages.get(lang)
        if not payload:
            continue
        front = payload.get("front") or {}
        body = payload.get("body") or ""
        text = build_markdown(front, body)
        path = f"{validators.LANG_FOLDERS[lang]}/{section}/{filename}"
        if lang == "sr":
            err = validators.validate_filename(filename, section)
            if err:
                errors.append(err)
        if filename.startswith("_index"):
            errors.append("Aktivnost ne sme imati ime _index.md.")
            continue
        ferr, _ = validators.validate_front_matter_text(text, section)
        errors.extend(f"{path}: {e}" for e in ferr)
        op = "update" if path in tree_paths else "create"
        ops.append(
            {
                "op": op,
                "path": path,
                "content": text,
                "sha": existing_shas.get(lang) if op == "update" else None,
            }
        )
    if errors:
        return jsonify({"errors": errors}), 400
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify({"status": "ok", "count": len(store.list())})


@app.route("/api/pending/activity-delete", methods=["POST"])
def api_pending_activity_delete():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    section = data.get("section")
    filename = data.get("filename")
    mode = data.get("mode", "draft")  # draft | delete
    if section not in ("events", "blog") or not filename:
        return jsonify({"error": "Nedostaje section/filename."}), 400

    client = get_client()
    store = get_store()
    tree_paths = {e["path"] for e in client.get_tree()}
    ops = []
    for lang, lang_dir in validators.LANG_FOLDERS.items():
        path = f"{lang_dir}/{section}/{filename}"
        if path not in tree_paths:
            continue
        try:
            text, sha = read_text_cached(client, path)
        except GitHubError:
            continue
        if mode == "delete":
            ops.append({"op": "delete", "path": path, "sha": sha})
        else:
            new_text = merge_front_matter(text, {"draft": True})
            ops.append({"op": "update", "path": path, "content": new_text, "sha": sha})
    if not ops:
        return jsonify({"error": "Aktivnost ne postoji ni u jednom jeziku."}), 404
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify({"status": "ok", "count": len(store.list())})


@app.route("/api/pending/activity-rename", methods=["POST"])
def api_pending_activity_rename():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    section = data.get("section")
    filename = data.get("filename")
    new_filename = data.get("new_filename")
    if section not in ("events", "blog") or not filename or not new_filename:
        return jsonify({"error": "Nedostaje section/filename/new_filename."}), 400
    err = validators.validate_filename(new_filename, section)
    if err:
        return jsonify({"errors": [err]}), 400

    client = get_client()
    store = get_store()
    tree_paths = {e["path"] for e in client.get_tree()}
    ops = []
    for lang, lang_dir in validators.LANG_FOLDERS.items():
        old_path = f"{lang_dir}/{section}/{filename}"
        new_path = f"{lang_dir}/{section}/{new_filename}"
        if new_path in tree_paths:
            return jsonify({"errors": [f"Fajl '{new_path}' već postoji."]}), 400
        if old_path in tree_paths:
            try:
                text, sha = read_text_cached(client, old_path)
            except GitHubError:
                continue
            ops.append({"op": "create", "path": new_path, "content": text})
            ops.append({"op": "delete", "path": old_path, "sha": sha})
    if not ops:
        return jsonify({"error": "Aktivnost ne postoji."}), 404
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify({"status": "ok", "count": len(store.list())})


@app.route("/api/pending/board", methods=["POST"])
def api_pending_board():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    languages = data.get("languages") or {}  # lang -> {members: [...]}
    client = get_client()
    store = get_store()
    ops = []
    errors = []
    for lang, payload in languages.items():
        if lang not in validators.LANG_FOLDERS:
            errors.append(f"Nepoznat jezik: {lang}")
            continue
        path = f"{validators.LANG_FOLDERS[lang]}/about/board.md"
        try:
            text, sha = read_text_cached(client, path)
        except GitHubError:
            errors.append(f"Nema fajla {path}")
            continue
        members = payload.get("members")
        if members is None:
            errors.append(f"{lang}: nedostaje members[].")
            continue
        new_text = merge_front_matter(text, {"members": members})
        ops.append({"op": "update", "path": path, "content": new_text, "sha": sha})
    if errors:
        return jsonify({"errors": errors}), 400
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify({"status": "ok", "count": len(store.list())})


@app.route("/api/pending/docs", methods=["POST"])
def api_pending_docs():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    languages = data.get("languages") or {}
    client = get_client()
    store = get_store()
    ops = []
    errors = []
    for lang, payload in languages.items():
        if lang not in validators.LANG_FOLDERS:
            errors.append(f"Nepoznat jezik: {lang}")
            continue
        path = f"{validators.LANG_FOLDERS[lang]}/documents/_index.md"
        try:
            text, sha = read_text_cached(client, path)
        except GitHubError:
            errors.append(f"Nema fajla {path}")
            continue
        docs = payload.get("docs")
        if docs is None:
            errors.append(f"{lang}: nedostaje docs[].")
            continue
        new_text = merge_front_matter(text, {"docs": docs})
        ops.append({"op": "update", "path": path, "content": new_text, "sha": sha})
    if errors:
        return jsonify({"errors": errors}), 400
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify({"status": "ok", "count": len(store.list())})


@app.route("/api/pending/page", methods=["POST"])
def api_pending_page():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    section = data.get("section")
    filename = data.get("filename")  # optional: guide subpages use this
    languages = data.get("languages") or {}  # lang -> {front: {...}, body: "..."}
    client = get_client()
    store = get_store()
    ops = []
    errors = []
    for lang, payload in languages.items():
        if lang not in validators.LANG_FOLDERS:
            errors.append(f"Nepoznat jezik: {lang}")
            continue
        if section in ("about", "alumni", "support", "join", "contact", "media", "documents"):
            path = f"{validators.LANG_FOLDERS[lang]}/{section}/_index.md"
        elif section == "guide" and filename:
            if not filename.endswith(".md"):
                errors.append("Ime fajla vodiča mora imati .md ekstenziju.")
                continue
            path = f"{validators.LANG_FOLDERS[lang]}/guide/{filename}"
        else:
            errors.append(f"Nepoznata sekcija: {section}")
            continue
        try:
            text, sha = read_text_cached(client, path)
        except GitHubError:
            errors.append(f"Nema fajla {path}")
            continue
        from markdown_parser import parse_front_matter, split_front_matter

        front = parse_front_matter(text)
        front.update(payload.get("front") or {})
        body = payload.get("body")
        if body is None:
            _, body, _ = split_front_matter(text)
        new_text = build_markdown(front, body)
        ops.append({"op": "update", "path": path, "content": new_text, "sha": sha})
    if errors:
        return jsonify({"errors": errors}), 400
    store.add(ops, base_sha=data.get("base_sha") or client.get_head())
    return jsonify({"status": "ok", "count": len(store.list())})


@app.route("/api/pending/settings", methods=["POST"])
def api_pending_settings():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    client = get_client()
    text, sha = read_text_cached(client, "hugo.toml")
    try:
        new_text = repo_service.build_hugo_content(
            text, data.get("params"), data.get("contact")
        )
    except ValueError as exc:
        return jsonify({"errors": [str(exc)]}), 400
    get_store().add(
        [{"op": "update", "path": "hugo.toml", "content": new_text, "sha": sha}],
        base_sha=data.get("base_sha") or client.get_head(),
    )
    return jsonify({"status": "ok", "count": len(get_store().list())})


@app.route("/api/pending/i18n", methods=["POST"])
def api_pending_i18n():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    lang = data.get("lang")
    updates = data.get("updates") or {}
    if lang not in ("sr", "en", "de"):
        return jsonify({"error": "Dozvoljeni jezici: sr, en, de."}), 400
    client = get_client()
    path = f"i18n/{lang}.yaml"
    try:
        text, sha = read_text_cached(client, path)
    except GitHubError as exc:
        return jsonify({"error": exc.message}), exc.status if exc.status in (400, 401, 403, 404, 409) else 502
    try:
        new_text = yaml_set_values(text, updates)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400
    get_store().add(
        [{"op": "update", "path": path, "content": new_text, "sha": sha}],
        base_sha=data.get("base_sha") or client.get_head(),
    )
    return jsonify({"status": "ok", "count": len(get_store().list())})


# ----------------------------------------------------------------- commit
@app.route("/api/commit", methods=["POST"])
def api_commit():
    auth = _require_auth()
    if auth:
        return auth
    data = request.get_json(silent=True) or {}
    try:
        result = repo_service.commit_pending(get_client(), get_store(), data.get("message"))
        _IMAGE_CACHE.clear()
        return jsonify({"status": "ok", **result})
    except ConflictError as exc:
        return jsonify({"error": str(exc), "conflict": True}), 409
    except GitHubError as exc:
        return jsonify({"error": exc.message}), exc.status if exc.status in (400, 401, 403, 404, 409) else 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
