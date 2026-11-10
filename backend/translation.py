"""
Pluggable machine-translation layer (sr -> en / de).

Free, keyless providers (no API key, no payment):
    google    - public Google Translate endpoint (client=gtx), default
    mymemory  - MyMemory API (api.mymemory.translated.net)
    mock      - development stub (prefixes text)
    none      - translation disabled

Optional paid/AI providers (still available if configured):
    openai    - OpenAI-compatible /chat/completions
    gemini    - Google Gemini generateContent

Provider is chosen through environment variables:
    TRANSLATION_PROVIDER = google (default) | mymemory | mock | none | openai | gemini
    TRANSLATION_API_KEY  = API key (only for openai/gemini)
    TRANSLATION_API_URL  = optional override (OpenAI-compatible endpoint)
    TRANSLATION_MODEL    = model name (only for openai/gemini)
"""
import os

import requests

TARGETS = {"en", "de"}

# Google/MyMemory free endpoints limit query sizes; bodies are split on
# paragraph boundaries into chunks that stay under these lengths.
# MyMemory's anonymous tier caps each request at ~500 chars.
GOOGLE_CHUNK_LIMIT = 1400
MYMEMORY_CHUNK_LIMIT = 400


class TranslationError(Exception):
    pass


class TranslationProvider:
    name = "base"

    def translate(self, texts, target_lang):
        """Translate a list of strings to target_lang; returns list of strings."""
        raise NotImplementedError


# ------------------------------------------------------------------- utils
def _split_long_paragraph(paragraph, limit):
    """Split an over-long paragraph on word boundaries into limit-sized pieces."""
    if len(paragraph) <= limit:
        return [paragraph]
    pieces = []
    current = ""
    for word in paragraph.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > limit and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    # Pathological case: a single word longer than the limit — hard slice.
    final = []
    for piece in pieces:
        while len(piece) > limit:
            final.append(piece[:limit])
            piece = piece[limit:]
        final.append(piece)
    return final


def _chunks(text, limit):
    """Split text into URL-safe chunks. Returns (chunks, separators) where
    separators[i] joins chunks[i] to chunks[i+1] (' ' inside a paragraph,
    '\n\n' between paragraphs)."""
    paragraphs = (text or "").split("\n\n")
    chunks, separators = [], []
    for i, paragraph in enumerate(paragraphs):
        pieces = _split_long_paragraph(paragraph, limit)
        for j, piece in enumerate(pieces):
            chunks.append(piece)
            if j + 1 < len(pieces):
                separators.append(" ")
            elif i + 1 < len(paragraphs):
                separators.append("\n\n")
            else:
                separators.append("")
    if not chunks:
        return [""], [""]
    return chunks, separators


def _translate_chunked(translate_one, text, target_lang, limit):
    """Translate one text (possibly long) by chunks, preserving paragraphs."""
    if not text:
        return text
    chunks, separators = _chunks(text, limit)
    translated = [translate_one(chunk, target_lang) for chunk in chunks]
    return "".join(t + sep for t, sep in zip(translated, separators))


def _redact(text, *secrets_):
    """Mask API keys that may appear in URLs or provider error bodies."""
    text = str(text)
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "***")
    return text


def _http_get(url, params, timeout=30):
    try:
        return requests.get(
            url,
            params=params,
            headers={"User-Agent": "VSS-Hugo-Admin-Tool/1.0"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise TranslationError(f"Prevodni servis nije dostupan: {exc}") from exc


# -------------------------------------------------------------- providers
class NoneProvider(TranslationProvider):
    name = "none"

    def translate(self, texts, target_lang):
        raise TranslationError(
            "Automatski prevod je isključen (TRANSLATION_PROVIDER=none). "
            "Postavi TRANSLATION_PROVIDER=google za besplatan prevod bez ključa."
        )


class MockProvider(TranslationProvider):
    name = "mock"

    def translate(self, texts, target_lang):
        return [f"[{target_lang}] {t}" if t else t for t in texts]


class GoogleTranslateProvider(TranslationProvider):
    """Free, keyless Google Translate endpoint (client=gtx)."""

    name = "google"
    API = "https://translate.googleapis.com/translate_a/single"

    def translate_one(self, text, target_lang):
        resp = _http_get(
            self.API,
            {
                "client": "gtx",
                "sl": "sr",
                "tl": target_lang,
                "dt": "t",
                "q": text,
            },
        )
        if resp.status_code != 200:
            raise TranslationError(
                f"Google prevod je vratio status {resp.status_code}. "
                "Pokušaj ponovo za koji minut (besplatni endpoint ima limite)."
            )
        try:
            data = resp.json()
            translated = "".join(
                segment[0] for segment in data[0] if segment and segment[0]
            )
        except (ValueError, IndexError, TypeError) as exc:
            raise TranslationError("Neočekivan odgovor Google prevoda.") from exc
        if not translated:
            raise TranslationError("Google prevod je vratio prazan rezultat.")
        return translated

    def translate(self, texts, target_lang):
        return [
            _translate_chunked(self.translate_one, t, target_lang, GOOGLE_CHUNK_LIMIT)
            for t in texts
        ]


class MyMemoryProvider(TranslationProvider):
    """Free MyMemory API (anonymous tier, daily limit)."""

    name = "mymemory"
    API = "https://api.mymemory.translated.net/get"

    def translate_one(self, text, target_lang):
        resp = _http_get(
            self.API,
            {"q": text, "langpair": f"sr|{target_lang}"},
        )
        if resp.status_code != 200:
            raise TranslationError(f"MyMemory je vratio status {resp.status_code}.")
        try:
            translated = (
                resp.json().get("responseData", {}).get("translatedText") or ""
            )
        except ValueError as exc:
            raise TranslationError("Neočekivan odgovor MyMemory servisa.") from exc
        upper = translated.upper()
        if "YOU USED ALL AVAILABLE FREE TRANSLATIONS" in upper:
            raise TranslationError(
                "MyMemory dnevni besplatni limit je iskorišćen — pokušaj kasnije."
            )
        if "QUERY LENGTH LIMIT EXCEEDED" in upper or "INVALID SOURCE LANGUAGE" in upper:
            raise TranslationError(translated)
        if not translated:
            raise TranslationError("MyMemory je vratio prazan rezultat.")
        return translated

    def translate(self, texts, target_lang):
        return [
            _translate_chunked(self.translate_one, t, target_lang, MYMEMORY_CHUNK_LIMIT)
            for t in texts
        ]


class FreeTranslateProvider(TranslationProvider):
    """Default provider: Google first, MyMemory as automatic fallback."""

    name = "google"

    def __init__(self):
        self.google = GoogleTranslateProvider()
        self.mymemory = MyMemoryProvider()

    def translate(self, texts, target_lang):
        try:
            return self.google.translate(texts, target_lang)
        except TranslationError as google_err:
            try:
                return self.mymemory.translate(texts, target_lang)
            except TranslationError:
                raise TranslationError(
                    f"{google_err} Ni fallback servis (MyMemory) nije uspeo — "
                    "pokušaj ponovo kasnije."
                ) from google_err


# ------------------------------------------------- optional AI providers
class OpenAIChatProvider(TranslationProvider):
    name = "openai"

    def __init__(self, api_key, model=None, api_url=None):
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        self.api_url = (api_url or "https://api.openai.com/v1/chat/completions").rstrip("/")

    def translate(self, texts, target_lang):
        system = (
            "You are a translator for a Serbian student association website. "
            "Translate the user messages from Serbian to the target language. "
            "Preserve Markdown syntax, URLs and line breaks. Return exactly one "
            "translated string per input string, in the same order, separated "
            "by a line containing only '@@'."
        )
        user = "\n@@\n".join(texts)
        try:
            resp = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise TranslationError(
                f"Prevozni servis nije dostupan: {_redact(exc, self.api_key)}"
            ) from exc
        if resp.status_code != 200:
            raise TranslationError(
                f"Prevodni servis je vratio {resp.status_code}: "
                f"{_redact(resp.text[:200], self.api_key)}"
            )
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise TranslationError("Neočekivan odgovor prevodnog servisa.") from exc
        return _split_result(content, len(texts))


class GeminiProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, api_key, model=None):
        self.api_key = api_key
        self.model = model or "gemini-2.0-flash"

    def translate(self, texts, target_lang):
        system = (
            "You are a translator for a Serbian student association website. "
            f"Translate the user messages from Serbian to {target_lang}. "
            "Preserve Markdown syntax, URLs and line breaks. Return exactly one "
            "translated string per input string, in the same order, separated "
            "by a line containing only '@@'."
        )
        user = "\n@@\n".join(texts)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        try:
            resp = requests.post(
                url,
                headers={"x-goog-api-key": self.api_key},
                json={
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"parts": [{"text": user}]}],
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise TranslationError(
                f"Prevozni servis nije dostupan: {_redact(exc, self.api_key)}"
            ) from exc
        if resp.status_code != 200:
            raise TranslationError(
                f"Prevodni servis je vratio {resp.status_code}: "
                f"{_redact(resp.text[:200], self.api_key)}"
            )
        try:
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            raise TranslationError("Neočekivan odgovor prevodnog servisa.") from exc
        return _split_result(content, len(texts))


def _split_result(content, expected):
    parts = [p.strip() for p in content.split("@@")]
    parts = [p for p in parts if p]
    if len(parts) != expected:
        raise TranslationError(
            f"Prevodni servis je vratio {len(parts)} delova, očekivano {expected}. Pokušaj ponovo."
        )
    return parts


_PROVIDERS = {
    "none": lambda: NoneProvider(),
    "mock": lambda: MockProvider(),
    "google": lambda: FreeTranslateProvider(),
    "mymemory": lambda: MyMemoryProvider(),
    "openai": lambda: OpenAIChatProvider(
        os.environ.get("TRANSLATION_API_KEY", ""),
        os.environ.get("TRANSLATION_MODEL"),
        os.environ.get("TRANSLATION_API_URL"),
    ),
    "gemini": lambda: GeminiProvider(
        os.environ.get("TRANSLATION_API_KEY", ""),
        os.environ.get("TRANSLATION_MODEL"),
    ),
}


def get_provider():
    """Instantiate the configured provider. Default: free Google (keyless)."""
    name = (os.environ.get("TRANSLATION_PROVIDER") or "google").lower()
    if name not in _PROVIDERS:
        name = "google"
    return _PROVIDERS[name]()
