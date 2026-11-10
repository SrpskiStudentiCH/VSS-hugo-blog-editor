"""
Tests: free translation providers (Google endpoint + MyMemory fallback).
HTTP is mocked — no network calls in tests.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import translation
from translation import (
    FreeTranslateProvider,
    GoogleTranslateProvider,
    MYMEMORY_CHUNK_LIMIT,
    MockProvider,
    MyMemoryProvider,
    TranslationError,
    _chunks,
    get_provider,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def google_ok(*texts):
    """Build a Google translate_a/single response for several chunks."""
    return [[[t, ""] for t in texts], None, "sr"]


class TestChunking(unittest.TestCase):
    def test_short_text_single_chunk(self):
        chunks, separators = _chunks("kratak tekst", 1400)
        self.assertEqual(chunks, ["kratak tekst"])
        self.assertEqual(separators, [""])

    def test_long_text_splits_on_paragraphs(self):
        paragraphs = ["paragraf " + "x" * 500 for _ in range(5)]
        text = "\n\n".join(paragraphs)
        chunks, separators = _chunks(text, 1400)
        self.assertGreater(len(chunks), 1)
        rebuilt = "".join(c + s for c, s in zip(chunks, separators))
        self.assertEqual(rebuilt, text)  # round-trip

    def test_oversized_paragraph_splits_by_words(self):
        paragraph = " ".join(["rec"] * 300)  # 1200 chars, no paragraph breaks
        chunks, separators = _chunks(paragraph, 400)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 400)
        rebuilt = "".join(c + s for c, s in zip(chunks, separators))
        self.assertEqual(rebuilt, paragraph)

    def test_empty(self):
        chunks, _ = _chunks("", 400)
        self.assertEqual(chunks, [""])


class TestGoogleProvider(unittest.TestCase):
    def test_parses_response(self):
        with patch(
            "translation.requests.get",
            return_value=FakeResponse(payload=google_ok("Hello world")),
        ) as get_mock:
            result = GoogleTranslateProvider().translate(["Zdravo svete"], "en")
        self.assertEqual(result, ["Hello world"])
        self.assertEqual(get_mock.call_args[1]["params"]["sl"], "sr")
        self.assertEqual(get_mock.call_args[1]["params"]["tl"], "en")

    def test_long_body_preserves_paragraphs(self):
        paragraphs = ["Od " + "a" * 1000, "Do " + "b" * 1000]
        responses = iter(
            [
                FakeResponse(payload=google_ok("From " + "c" * 1000)),
                FakeResponse(payload=google_ok("To " + "d" * 1000)),
            ]
        )
        with patch("translation.requests.get", side_effect=lambda *a, **k: next(responses)):
            result = GoogleTranslateProvider().translate(
                ["\n\n".join(paragraphs)], "en"
            )
        self.assertTrue(result[0].startswith("From"))
        self.assertIn("\n\n", result[0])

    def test_http_error_raises(self):
        with patch(
            "translation.requests.get", return_value=FakeResponse(status_code=429)
        ):
            with self.assertRaises(TranslationError):
                GoogleTranslateProvider().translate(["x"], "en")


class TestMyMemoryProvider(unittest.TestCase):
    def test_parses_response(self):
        with patch(
            "translation.requests.get",
            return_value=FakeResponse(
                payload={"responseData": {"translatedText": "Hallo Welt"}}
            ),
        ):
            result = MyMemoryProvider().translate(["Zdravo"], "de")
        self.assertEqual(result, ["Hallo Welt"])

    def test_daily_limit_message(self):
        payload = {
            "responseData": {
                "translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY"
            }
        }
        with patch(
            "translation.requests.get", return_value=FakeResponse(payload=payload)
        ):
            with self.assertRaises(TranslationError) as ctx:
                MyMemoryProvider().translate(["x"], "en")
        self.assertIn("limit", ctx.exception.args[0])

    def test_small_chunks_respect_request_limit(self):
        """MyMemory free tier caps each request — chunks must stay small."""
        paragraphs = [" ".join(["rec"] * 250), " ".join(["rec"] * 250)]
        queries = []

        def fake_get(url, **kwargs):
            queries.append(kwargs["params"]["q"])
            return FakeResponse(payload={"responseData": {"translatedText": "X"}})

        with patch("translation.requests.get", side_effect=fake_get):
            MyMemoryProvider().translate(["\n\n".join(paragraphs)], "en")
        self.assertGreaterEqual(len(queries), 4)  # 2 x 1000 chars -> >=4 chunks
        for query in queries:
            self.assertLessEqual(len(query), MYMEMORY_CHUNK_LIMIT)


class TestFreeFallback(unittest.TestCase):
    def test_google_failure_falls_back_to_mymemory(self):
        def fake_get(url, **kwargs):
            if "translate.googleapis" in url:
                return FakeResponse(status_code=500)
            return FakeResponse(payload={"responseData": {"translatedText": "Fallback ok"}})

        with patch("translation.requests.get", side_effect=fake_get):
            result = FreeTranslateProvider().translate(["x"], "en")
        self.assertEqual(result, ["Fallback ok"])

    def test_both_fail_raises_clear_error(self):
        with patch(
            "translation.requests.get", return_value=FakeResponse(status_code=500)
        ):
            with self.assertRaises(TranslationError) as ctx:
                FreeTranslateProvider().translate(["x"], "en")
        self.assertIn("MyMemory", ctx.exception.args[0])


class TestProviderSelection(unittest.TestCase):
    def test_default_is_free_google(self):
        with patch.dict(os.environ):
            os.environ.pop("TRANSLATION_PROVIDER", None)
            provider = get_provider()
        self.assertIsInstance(provider, FreeTranslateProvider)

    def test_mock_selected(self):
        with patch.dict(os.environ, {"TRANSLATION_PROVIDER": "mock"}):
            self.assertIsInstance(get_provider(), MockProvider)

    def test_unknown_falls_back_to_google(self):
        with patch.dict(os.environ, {"TRANSLATION_PROVIDER": "nepoznat"}):
            self.assertIsInstance(get_provider(), FreeTranslateProvider)

    def test_mock_translate(self):
        self.assertEqual(
            MockProvider().translate(["a", ""], "de"), ["[de] a", ""]
        )


if __name__ == "__main__":
    unittest.main()
