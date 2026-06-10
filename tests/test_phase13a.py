"""Phase 13A ship test - transcription provider abstraction.

Verifies:

  13A.1 - Registry
     - Built-in providers (assemblyai, deepgram) are registered on import
     - get_provider_by_name returns the right instance
     - get_provider_by_name raises with available list on unknown name
     - get_active_provider respects settings.TRANSCRIPTION_PROVIDER

  13A.2 - AssemblyAIProvider
     - recall_provider_key matches Recall.ai's expected slug
     - build_recording_config returns the existing payload shape
     - Language ignored (provider doesn't support pinning)
     - extract_language_code reads provider_data.language_code
     - extract_language_code falls back to data.language

  13A.3 - DeepgramProvider
     - recall_provider_key is 'deepgram_streaming'
     - 'auto' / 'multi' both -> language='multi'
     - 'hi' / 'hi-IN' both -> language='hi'
     - 'en-US' -> language='en'
     - Empty/invalid -> language='multi' (safe fallback)
     - smart_format + punctuate ON, diarize OFF
     - Model defaults to settings.DEEPGRAM_MODEL
     - extract_language_code reads provider_data.language
     - extract_language_code falls back to detected_language / data.language

  13A.4 - Integration with RecallService.create_bot
     - Bot payload uses the active provider's recall_provider_key
     - Bot payload uses the active provider's recording_config shape
     - Per-call `language=` override is honored

Run with:

    venv\\Scripts\\python.exe tests\\test_phase13a.py
"""
from __future__ import annotations

import os
import sys
import traceback
from contextlib import contextmanager
from typing import Callable, List, Tuple
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


results: List[Tuple[str, str, str, str]] = []


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(slice_id: str, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as e:
        msg = str(e) or "assertion failed"
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [FAIL] {name} :: {msg}")
        return
    except Exception:
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# 13A.1 - Registry
# ---------------------------------------------------------------------------

def test_builtin_providers_registered():
    from app.services.transcription import registry
    # Built-in providers self-register on import.
    assert "assemblyai" in registry._REGISTRY
    assert "deepgram" in registry._REGISTRY


def test_get_provider_by_name_returns_right_instance():
    from app.services.transcription import get_provider_by_name
    aa = get_provider_by_name("assemblyai")
    dg = get_provider_by_name("deepgram")
    assert aa.name == "assemblyai"
    assert dg.name == "deepgram"
    assert aa is not dg


def test_get_provider_by_name_unknown_raises():
    from app.services.transcription import get_provider_by_name
    try:
        get_provider_by_name("nonexistent")
        assert False, "should have raised"
    except ValueError as e:
        msg = str(e)
        assert "nonexistent" in msg
        assert "Available:" in msg
        assert "assemblyai" in msg
        assert "deepgram" in msg


def test_get_active_provider_respects_setting():
    from app.config import settings as settings_mod
    from app.services.transcription import get_active_provider
    original = settings_mod.settings.TRANSCRIPTION_PROVIDER
    try:
        settings_mod.settings.TRANSCRIPTION_PROVIDER = "deepgram"
        assert get_active_provider().name == "deepgram"
        settings_mod.settings.TRANSCRIPTION_PROVIDER = "assemblyai"
        assert get_active_provider().name == "assemblyai"
    finally:
        settings_mod.settings.TRANSCRIPTION_PROVIDER = original


# ---------------------------------------------------------------------------
# 13A.2 - AssemblyAIProvider
# ---------------------------------------------------------------------------

def test_assemblyai_recall_key_and_config_shape():
    from app.services.transcription.assemblyai_provider import AssemblyAIProvider
    p = AssemblyAIProvider()
    assert p.recall_provider_key == "assembly_ai_v3_streaming"
    cfg = p.build_recording_config()
    assert cfg["speech_model"] == "universal-streaming-multilingual"
    assert cfg["language_detection"] is True
    assert cfg["format_turns"] is True


def test_assemblyai_ignores_explicit_language():
    """AssemblyAI streaming doesn't accept a pinned language; we don't
    pass one. Caller can still ask for 'hi' or anything else without
    crashing."""
    from app.services.transcription.assemblyai_provider import AssemblyAIProvider
    p = AssemblyAIProvider()
    cfg_auto = p.build_recording_config("auto")
    cfg_hi = p.build_recording_config("hi")
    # Same config either way — language is ignored.
    assert cfg_auto == cfg_hi


def test_assemblyai_extract_language_from_provider_data():
    from app.services.transcription.assemblyai_provider import AssemblyAIProvider
    p = AssemblyAIProvider()
    payload = {"data": {"provider_data": {"language_code": "EN"}}}
    assert p.extract_language_code(payload) == "en"  # lowercased


def test_assemblyai_extract_language_fallback():
    from app.services.transcription.assemblyai_provider import AssemblyAIProvider
    p = AssemblyAIProvider()
    payload = {"data": {"language": "es"}}
    assert p.extract_language_code(payload) == "es"


def test_assemblyai_extract_language_missing_returns_none():
    from app.services.transcription.assemblyai_provider import AssemblyAIProvider
    p = AssemblyAIProvider()
    assert p.extract_language_code({}) is None
    assert p.extract_language_code({"data": {}}) is None


# ---------------------------------------------------------------------------
# 13A.3 - DeepgramProvider
# ---------------------------------------------------------------------------

def test_deepgram_recall_key():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    assert DeepgramProvider().recall_provider_key == "deepgram_streaming"


def test_deepgram_auto_means_multi():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    assert p.build_recording_config("auto")["language"] == "multi"
    assert p.build_recording_config("multi")["language"] == "multi"
    assert p.build_recording_config("")["language"] == "multi"
    assert p.build_recording_config(None)["language"] == "multi"  # type: ignore[arg-type]


def test_deepgram_explicit_hindi():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    assert p.build_recording_config("hi")["language"] == "hi"
    # BCP-47 region stripped:
    assert p.build_recording_config("hi-IN")["language"] == "hi"
    assert p.build_recording_config("HI-IN")["language"] == "hi"


def test_deepgram_explicit_english():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    assert p.build_recording_config("en")["language"] == "en"
    assert p.build_recording_config("en-US")["language"] == "en"


def test_deepgram_invalid_fallback_to_multi():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    # Too long / weird codes -> multi
    assert p.build_recording_config("verylongstring")["language"] == "multi"


def test_deepgram_config_has_smart_format_and_no_diarize():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    cfg = DeepgramProvider().build_recording_config("multi")
    assert cfg["smart_format"] is True
    assert cfg["punctuate"] is True
    # diarize is False — Recall handles speaker attribution
    assert cfg["diarize"] is False


def test_deepgram_model_from_settings():
    from app.config import settings as settings_mod
    from app.services.transcription.deepgram_provider import DeepgramProvider
    original = settings_mod.settings.DEEPGRAM_MODEL
    try:
        settings_mod.settings.DEEPGRAM_MODEL = "nova-3"
        assert DeepgramProvider().build_recording_config()["model"] == "nova-3"
        settings_mod.settings.DEEPGRAM_MODEL = "nova-2"
        assert DeepgramProvider().build_recording_config()["model"] == "nova-2"
    finally:
        settings_mod.settings.DEEPGRAM_MODEL = original


def test_deepgram_extract_language_from_provider_data():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    payload = {"data": {"provider_data": {"language": "HI"}}}
    assert p.extract_language_code(payload) == "hi"


def test_deepgram_extract_language_detected_language_field():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    # Some Deepgram responses use `detected_language` instead.
    payload = {"data": {"provider_data": {"detected_language": "en"}}}
    assert p.extract_language_code(payload) == "en"


def test_deepgram_extract_language_fallback_to_data_language():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    payload = {"data": {"language": "es"}}
    assert p.extract_language_code(payload) == "es"


def test_deepgram_extract_language_missing_returns_none():
    from app.services.transcription.deepgram_provider import DeepgramProvider
    p = DeepgramProvider()
    assert p.extract_language_code({}) is None


# ---------------------------------------------------------------------------
# 13A.4 - Integration with RecallService.create_bot
# ---------------------------------------------------------------------------

def test_create_bot_uses_active_provider_assemblyai():
    """When provider=assemblyai, bot payload has the AssemblyAI block."""
    from app.config import settings as settings_mod
    from app.services.recall_ai_service import RecallService

    original = settings_mod.settings.TRANSCRIPTION_PROVIDER
    settings_mod.settings.TRANSCRIPTION_PROVIDER = "assemblyai"

    captured = {}
    with patch("app.services.recall_ai_service.requests") as mock_requests:
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "bot_test"}
        resp.raise_for_status.return_value = None
        def capture_post(url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return resp
        mock_requests.post.side_effect = capture_post

        svc = RecallService()
        try:
            svc.create_bot("https://meet.google.com/test", 12345)
        finally:
            settings_mod.settings.TRANSCRIPTION_PROVIDER = original

    provider_dict = captured["json"]["recording_config"]["transcript"]["provider"]
    assert "assembly_ai_v3_streaming" in provider_dict
    assert provider_dict["assembly_ai_v3_streaming"]["speech_model"] == \
        "universal-streaming-multilingual"
    assert "deepgram_streaming" not in provider_dict


def test_create_bot_uses_active_provider_deepgram():
    from app.config import settings as settings_mod
    from app.services.recall_ai_service import RecallService

    original = settings_mod.settings.TRANSCRIPTION_PROVIDER
    settings_mod.settings.TRANSCRIPTION_PROVIDER = "deepgram"

    captured = {}
    with patch("app.services.recall_ai_service.requests") as mock_requests:
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "bot_test"}
        resp.raise_for_status.return_value = None
        def capture_post(url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return resp
        mock_requests.post.side_effect = capture_post

        svc = RecallService()
        try:
            svc.create_bot("https://meet.google.com/test", 12345)
        finally:
            settings_mod.settings.TRANSCRIPTION_PROVIDER = original

    provider_dict = captured["json"]["recording_config"]["transcript"]["provider"]
    assert "deepgram_streaming" in provider_dict
    assert "assembly_ai_v3_streaming" not in provider_dict
    dg_cfg = provider_dict["deepgram_streaming"]
    assert dg_cfg["model"] == "nova-3"
    assert dg_cfg["language"] == "multi"  # default 'auto' -> 'multi'


def test_create_bot_per_call_language_override():
    """Caller can pin to a specific language regardless of the workspace default."""
    from app.config import settings as settings_mod
    from app.services.recall_ai_service import RecallService

    original_prov = settings_mod.settings.TRANSCRIPTION_PROVIDER
    original_lang = settings_mod.settings.TRANSCRIPTION_LANGUAGE
    settings_mod.settings.TRANSCRIPTION_PROVIDER = "deepgram"
    settings_mod.settings.TRANSCRIPTION_LANGUAGE = "en"  # workspace default

    captured = {}
    with patch("app.services.recall_ai_service.requests") as mock_requests:
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "bot_test"}
        resp.raise_for_status.return_value = None
        def capture_post(url, json=None, headers=None):
            captured["json"] = json
            return resp
        mock_requests.post.side_effect = capture_post

        svc = RecallService()
        try:
            # Per-call override: this specific meeting is Hindi.
            svc.create_bot(
                "https://meet.google.com/test", 12345, language="hi-IN",
            )
        finally:
            settings_mod.settings.TRANSCRIPTION_PROVIDER = original_prov
            settings_mod.settings.TRANSCRIPTION_LANGUAGE = original_lang

    dg_cfg = captured["json"]["recording_config"]["transcript"]["provider"][
        "deepgram_streaming"
    ]
    assert dg_cfg["language"] == "hi", (
        f"per-call override should win over workspace default; got {dg_cfg!r}"
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("13A.1 registry", [
            ("built-in providers registered", test_builtin_providers_registered),
            ("get_provider_by_name returns right instance", test_get_provider_by_name_returns_right_instance),
            ("unknown provider raises with available list", test_get_provider_by_name_unknown_raises),
            ("get_active_provider respects setting", test_get_active_provider_respects_setting),
        ]),
        ("13A.2 AssemblyAIProvider", [
            ("recall_key and config shape", test_assemblyai_recall_key_and_config_shape),
            ("ignores explicit language", test_assemblyai_ignores_explicit_language),
            ("extract language from provider_data", test_assemblyai_extract_language_from_provider_data),
            ("extract language fallback to data.language", test_assemblyai_extract_language_fallback),
            ("missing language returns None", test_assemblyai_extract_language_missing_returns_none),
        ]),
        ("13A.3 DeepgramProvider", [
            ("recall_key is deepgram_streaming", test_deepgram_recall_key),
            ("auto -> language=multi", test_deepgram_auto_means_multi),
            ("explicit Hindi (hi / hi-IN)", test_deepgram_explicit_hindi),
            ("explicit English (en / en-US)", test_deepgram_explicit_english),
            ("invalid code falls back to multi", test_deepgram_invalid_fallback_to_multi),
            ("smart_format ON, diarize OFF", test_deepgram_config_has_smart_format_and_no_diarize),
            ("model from settings.DEEPGRAM_MODEL", test_deepgram_model_from_settings),
            ("extract language from provider_data.language", test_deepgram_extract_language_from_provider_data),
            ("extract language from detected_language field", test_deepgram_extract_language_detected_language_field),
            ("extract language fallback to data.language", test_deepgram_extract_language_fallback_to_data_language),
            ("missing language returns None", test_deepgram_extract_language_missing_returns_none),
        ]),
        ("13A.4 RecallService.create_bot", [
            ("uses assemblyai when configured", test_create_bot_uses_active_provider_assemblyai),
            ("uses deepgram when configured", test_create_bot_uses_active_provider_deepgram),
            ("per-call language override wins", test_create_bot_per_call_language_override),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 13A summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
