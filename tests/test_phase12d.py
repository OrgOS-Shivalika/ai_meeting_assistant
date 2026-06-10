"""Phase 12D ship test - TTS + Recall audio injection.

What this test covers:

  12D.1 - TTSService
     - Empty / whitespace text raises ValueError before any API call
     - First call hits the API and writes the cache
     - Second identical call returns cached bytes (no API call)
     - Different voice / model invalidates the cache
     - Provider returning empty bytes raises RuntimeError
     - Cache key is content-addressed and stable

  12D.2 - AudioPlayer
     - Happy path: upload -> play -> wait -> leave
     - Upload failure: returns 'upload_failed', still leaves call
     - StorageNotConfigured: returns 'storage_not_configured', still leaves
     - play_audio failure: returns 'playback_failed', still leaves call
     - wait_for_playback exception: returns 'timeout', still leaves call
     - wait_for_playback returns False: returns 'timeout', still leaves
     - leave_after=False: never calls leave_call
     - leave_call failure does NOT propagate to caller

  12D.3 - RecallService.play_audio + leave_call + wait_for_playback
     - play_audio: POSTs to /bot/{id}/output_audio/, surfaces error
     - leave_call: POSTs to /bot/{id}/leave_call/, swallows exceptions
     - wait_for_playback: returns True on 'done' status
     - wait_for_playback: returns False on 'failed' status
     - wait_for_playback: returns False on timeout
     - wait_for_playback with no playback_id: falls back to fixed sleep

Run with:

    venv\\Scripts\\python.exe tests\\test_phase12d.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback
import types
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
# Fake TTS provider — stand-in for OpenAI so tests never make real
# network calls. Counts calls so we can assert cache hits.
# ---------------------------------------------------------------------------

class _FakeTTSProvider:
    name = "fake"
    default_format = "mp3"
    default_content_type = "audio/mpeg"

    def __init__(self, audio_bytes: bytes = b"\xff\xfb\x90\x00fake-mp3-bytes"):
        self.audio_bytes = audio_bytes
        self.call_count = 0

    def synthesize(self, text: str, voice: str, model: str) -> bytes:
        self.call_count += 1
        # Return slightly different bytes per text so cache mismatch is detectable
        return self.audio_bytes + b" " + text.encode()[:16]


def _make_tts_service(provider: _FakeTTSProvider, cache_dir: str):
    """Build a TTSService with the fake provider + a temp cache dir."""
    from app.services.briefing.tts_service import TTSService
    # Clear the class-level provider registry so we know exactly what's installed.
    TTSService._providers.clear()
    TTSService.register(provider)

    # Patch the cache dir on the instance.
    svc = TTSService(provider_name=provider.name)
    svc._cache_dir = cache_dir
    return svc


# ---------------------------------------------------------------------------
# 12D.1 - TTSService
# ---------------------------------------------------------------------------

def test_tts_empty_text_raises():
    cache = tempfile.mkdtemp(prefix="tts-test-")
    try:
        svc = _make_tts_service(_FakeTTSProvider(), cache)
        try:
            svc.synthesize("")
            assert False, "empty text should raise"
        except ValueError:
            pass
        try:
            svc.synthesize("    ")
            assert False, "whitespace text should raise"
        except ValueError:
            pass
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def test_tts_first_call_hits_api_and_caches():
    cache = tempfile.mkdtemp(prefix="tts-test-")
    try:
        provider = _FakeTTSProvider()
        svc = _make_tts_service(provider, cache)
        r1 = svc.synthesize("Hello world", voice="nova", model="tts-1-hd")
        assert r1.cache_hit is False
        assert provider.call_count == 1
        assert r1.audio_bytes
        # Cache file should exist on disk
        path = svc._cache_path(r1.cache_key)
        assert os.path.isfile(path)
        # And contain the exact bytes
        with open(path, "rb") as f:
            assert f.read() == r1.audio_bytes
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def test_tts_second_call_returns_cached_no_api():
    cache = tempfile.mkdtemp(prefix="tts-test-")
    try:
        provider = _FakeTTSProvider()
        svc = _make_tts_service(provider, cache)
        r1 = svc.synthesize("Hello world", voice="nova", model="tts-1-hd")
        r2 = svc.synthesize("Hello world", voice="nova", model="tts-1-hd")
        assert r1.cache_hit is False
        assert r2.cache_hit is True
        assert provider.call_count == 1, f"expected 1 API call, got {provider.call_count}"
        assert r2.audio_bytes == r1.audio_bytes
        assert r2.cache_key == r1.cache_key
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def test_tts_voice_change_invalidates_cache():
    cache = tempfile.mkdtemp(prefix="tts-test-")
    try:
        provider = _FakeTTSProvider()
        svc = _make_tts_service(provider, cache)
        r1 = svc.synthesize("Hello world", voice="nova", model="tts-1-hd")
        r2 = svc.synthesize("Hello world", voice="echo", model="tts-1-hd")
        assert r1.cache_key != r2.cache_key
        assert provider.call_count == 2
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def test_tts_model_change_invalidates_cache():
    cache = tempfile.mkdtemp(prefix="tts-test-")
    try:
        provider = _FakeTTSProvider()
        svc = _make_tts_service(provider, cache)
        r1 = svc.synthesize("Hello world", voice="nova", model="tts-1")
        r2 = svc.synthesize("Hello world", voice="nova", model="tts-1-hd")
        assert r1.cache_key != r2.cache_key
        assert provider.call_count == 2
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def test_tts_empty_audio_bytes_raises():
    cache = tempfile.mkdtemp(prefix="tts-test-")
    try:
        provider = _FakeTTSProvider(audio_bytes=b"")
        # The fake will return b"" + b" hello world" - still non-empty.
        # Build a provider that ACTUALLY returns empty.
        class _EmptyProvider:
            name = "empty"
            default_format = "mp3"
            default_content_type = "audio/mpeg"
            def synthesize(self, text, voice, model):
                return b""

        from app.services.briefing.tts_service import TTSService
        TTSService._providers.clear()
        TTSService.register(_EmptyProvider())
        svc = TTSService(provider_name="empty")
        svc._cache_dir = cache
        try:
            svc.synthesize("Hello")
            assert False, "empty audio bytes should raise"
        except RuntimeError as e:
            assert "empty" in str(e).lower()
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def test_tts_unknown_provider_raises():
    from app.services.briefing.tts_service import TTSService
    TTSService._providers.clear()
    TTSService.register(_FakeTTSProvider())
    try:
        TTSService(provider_name="nonexistent")
        assert False, "unknown provider should raise"
    except ValueError as e:
        assert "not registered" in str(e)


# ---------------------------------------------------------------------------
# 12D.2 - AudioPlayer
# ---------------------------------------------------------------------------

def _make_tts_result(text: str = "test", cache_key: str = "abc123"):
    from app.services.briefing.tts_service import TTSResult
    return TTSResult(
        audio_bytes=b"\xff\xfb\x90\x00audio",
        content_type="audio/mpeg",
        format="mp3",
        provider="fake",
        model="tts-1-hd",
        voice="nova",
        char_count=len(text),
        cache_hit=False,
        cache_key=cache_key,
    )


def _make_recall_mock(
    *,
    play_returns=None,
    play_raises=None,
    wait_returns=True,
    wait_raises=None,
    leave_raises=None,
):
    """Build a mocked RecallService with controllable behavior."""
    mock = MagicMock()
    if play_raises:
        mock.play_audio.side_effect = play_raises
    else:
        mock.play_audio.return_value = play_returns or {"id": "pb_test"}
    if wait_raises:
        mock.wait_for_playback_complete.side_effect = wait_raises
    else:
        mock.wait_for_playback_complete.return_value = wait_returns
    if leave_raises:
        mock.leave_call.side_effect = leave_raises
    else:
        mock.leave_call.return_value = None
    return mock


def _patched_storage():
    """Context manager that swaps `storage` module-level singleton for a mock."""
    return patch("app.services.briefing.audio_player.storage")


def test_player_happy_path():
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock()
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/audio.mp3"
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "spoken"
        assert result.left_call is True
        assert result.audio_url == "https://s3.example/audio.mp3"
        assert result.playback_id == "pb_test"
        # Verify call sequence: upload, presign, play, wait, leave
        mock_storage.upload_bytes.assert_called_once()
        mock_storage.presigned_get_url.assert_called_once()
        recall.play_audio.assert_called_once()
        recall.wait_for_playback_complete.assert_called_once()
        recall.leave_call.assert_called_once_with("bot1")


def test_player_storage_not_configured_still_leaves():
    from app.services.briefing.audio_player import AudioPlayer
    from app.services.storage_service import StorageNotConfigured
    recall = _make_recall_mock()
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.side_effect = StorageNotConfigured("no s3")
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "storage_not_configured"
        assert result.left_call is True
        recall.leave_call.assert_called_once_with("bot1")
        recall.play_audio.assert_not_called()


def test_player_upload_failure_still_leaves():
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock()
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.side_effect = RuntimeError("S3 down")
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "upload_failed"
        assert result.left_call is True
        assert "S3 down" in result.error_message
        recall.leave_call.assert_called_once()
        recall.play_audio.assert_not_called()


def test_player_play_audio_failure_still_leaves():
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock(play_raises=RuntimeError("Recall 500"))
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/a.mp3"
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "playback_failed"
        assert result.left_call is True
        assert "Recall 500" in result.error_message
        recall.leave_call.assert_called_once()


def test_player_wait_for_playback_exception_still_leaves():
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock(wait_raises=RuntimeError("poll error"))
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/a.mp3"
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "timeout"
        assert result.left_call is True
        recall.leave_call.assert_called_once()


def test_player_wait_returns_false_still_leaves():
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock(wait_returns=False)
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/a.mp3"
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "timeout"
        assert result.left_call is True
        recall.leave_call.assert_called_once()


def test_player_leave_after_false_never_leaves():
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock()
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/a.mp3"
        player = AudioPlayer(recall_service=recall)
        result = player.deliver(
            bot_id="bot1", meeting_id=42, tts_result=_make_tts_result(),
            leave_after=False,
        )
        assert result.status == "spoken"
        assert result.left_call is False
        recall.leave_call.assert_not_called()


def test_player_leave_call_failure_does_not_propagate():
    from app.services.briefing.audio_player import AudioPlayer
    # Happy path otherwise, but leave_call raises.
    recall = _make_recall_mock(leave_raises=RuntimeError("network blip"))
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/a.mp3"
        player = AudioPlayer(recall_service=recall)
        # Must not raise — leave_call exceptions are the orchestrator's
        # last problem to worry about.
        result = player.deliver(bot_id="bot1", meeting_id=42, tts_result=_make_tts_result())
        assert result.status == "spoken"
        assert result.left_call is False  # We tried but it failed
        recall.leave_call.assert_called_once()


def test_player_storage_key_is_unique_per_call():
    """Calling deliver twice for the same script must produce different
    storage keys, so the second attempt doesn't overwrite the first."""
    from app.services.briefing.audio_player import AudioPlayer
    recall = _make_recall_mock()
    keys = []
    with _patched_storage() as mock_storage:
        mock_storage.upload_bytes.return_value = None
        mock_storage.presigned_get_url.return_value = "https://s3.example/a.mp3"
        player = AudioPlayer(recall_service=recall)
        for _ in range(3):
            result = player.deliver(bot_id="b", meeting_id=1, tts_result=_make_tts_result())
            keys.append(result.audio_storage_key)
    assert len(set(keys)) == 3, f"keys should all differ; got {keys}"
    # But they should all start with the same prefix
    assert all(k.startswith("closing_briefings/1/") for k in keys)


# ---------------------------------------------------------------------------
# 12D.3 - RecallService HTTP wrappers
# ---------------------------------------------------------------------------

def _patched_requests():
    return patch("app.services.recall_ai_service.requests")


def test_recall_play_audio_posts_correctly():
    """play_audio MUST send b64_data inline, not a URL — Recall's
    output_audio endpoint does not fetch from URLs."""
    import base64
    from app.services.recall_ai_service import RecallService
    audio = b"\xff\xfb\x90\x00fake-mp3-bytes"
    with _patched_requests() as mock_requests:
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"id": "pb_abc"}'
        resp.json.return_value = {"id": "pb_abc"}
        resp.raise_for_status.return_value = None
        mock_requests.post.return_value = resp

        svc = RecallService()
        result = svc.play_audio("bot1", audio, kind="mp3")
        assert result["id"] == "pb_abc"
        mock_requests.post.assert_called_once()
        args, kwargs = mock_requests.post.call_args
        assert "/bot/bot1/output_audio/" in args[0]
        sent = kwargs["json"]
        assert sent["kind"] == "mp3"
        assert sent["b64_data"] == base64.b64encode(audio).decode("ascii")
        # url field must NOT be present — Recall rejects it.
        assert "url" not in sent


def test_recall_play_audio_empty_bytes_raises():
    from app.services.recall_ai_service import RecallService
    svc = RecallService()
    try:
        svc.play_audio("bot1", b"")
        assert False, "empty bytes should raise"
    except ValueError as e:
        assert "non-empty" in str(e)


def test_recall_play_audio_raises_on_error_status():
    from app.services.recall_ai_service import RecallService
    import requests as real_requests
    with _patched_requests() as mock_requests:
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "internal error"
        resp.raise_for_status.side_effect = real_requests.HTTPError("500")
        mock_requests.post.return_value = resp

        svc = RecallService()
        try:
            svc.play_audio("bot1", b"\xff\xfbaudio")
            assert False, "should have raised"
        except real_requests.HTTPError:
            pass


def test_recall_leave_call_swallows_exceptions():
    from app.services.recall_ai_service import RecallService
    with _patched_requests() as mock_requests:
        mock_requests.post.side_effect = RuntimeError("network down")
        svc = RecallService()
        # Must not raise — leave_call is "best effort, fire and forget."
        svc.leave_call("bot1")


def test_recall_wait_for_playback_returns_true_on_done():
    from app.services.recall_ai_service import RecallService
    svc = RecallService()
    with patch.object(svc, "get_bot") as mock_get:
        mock_get.return_value = {
            "output_media": [{"id": "pb_x", "status": {"code": "done"}}]
        }
        assert svc.wait_for_playback_complete("bot1", "pb_x", timeout=5) is True


def test_recall_wait_for_playback_returns_false_on_failed():
    from app.services.recall_ai_service import RecallService
    svc = RecallService()
    with patch.object(svc, "get_bot") as mock_get:
        mock_get.return_value = {
            "output_media": [{"id": "pb_x", "status": {"code": "failed"}}]
        }
        assert svc.wait_for_playback_complete("bot1", "pb_x", timeout=5) is False


def test_recall_wait_for_playback_returns_false_on_timeout():
    from app.services.recall_ai_service import RecallService
    svc = RecallService()
    with patch.object(svc, "get_bot") as mock_get:
        # Stays in "playing" status forever
        mock_get.return_value = {
            "output_media": [{"id": "pb_x", "status": {"code": "playing"}}]
        }
        t0 = time.time()
        result = svc.wait_for_playback_complete(
            "bot1", "pb_x", timeout=1, poll_interval_s=0.1,
        )
        elapsed = time.time() - t0
        assert result is False
        # Should respect the timeout (give it some slack for poll cycles)
        assert elapsed < 2.0, f"took {elapsed}s, expected ~1s"


def test_recall_wait_for_playback_no_id_falls_back_to_sleep():
    from app.services.recall_ai_service import RecallService
    svc = RecallService()
    # No playback_id provided — should sleep up to min(timeout, 90) and return True
    t0 = time.time()
    result = svc.wait_for_playback_complete("bot1", None, timeout=1)
    elapsed = time.time() - t0
    assert result is True
    # Should have actually slept ~1 second (not 90)
    assert 0.9 < elapsed < 2.0, f"took {elapsed}s, expected ~1s"


def test_recall_wait_for_playback_ignores_other_playback_ids():
    """If the response contains a different playback id, we should keep
    polling (not return on the wrong one)."""
    from app.services.recall_ai_service import RecallService
    svc = RecallService()
    poll_count = [0]
    def fake_get(bot_id):
        poll_count[0] += 1
        if poll_count[0] < 3:
            return {
                "output_media": [{"id": "DIFFERENT", "status": {"code": "done"}}]
            }
        return {
            "output_media": [{"id": "pb_x", "status": {"code": "done"}}]
        }
    with patch.object(svc, "get_bot", side_effect=fake_get):
        result = svc.wait_for_playback_complete(
            "bot1", "pb_x", timeout=5, poll_interval_s=0.05,
        )
    assert result is True
    assert poll_count[0] >= 3


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("12D.1 TTSService", [
            ("empty text raises", test_tts_empty_text_raises),
            ("first call hits API and caches", test_tts_first_call_hits_api_and_caches),
            ("second call returns cached, no API", test_tts_second_call_returns_cached_no_api),
            ("voice change invalidates cache", test_tts_voice_change_invalidates_cache),
            ("model change invalidates cache", test_tts_model_change_invalidates_cache),
            ("empty audio bytes raises", test_tts_empty_audio_bytes_raises),
            ("unknown provider raises", test_tts_unknown_provider_raises),
        ]),
        ("12D.2 AudioPlayer", [
            ("happy path", test_player_happy_path),
            ("storage not configured still leaves", test_player_storage_not_configured_still_leaves),
            ("upload failure still leaves", test_player_upload_failure_still_leaves),
            ("play_audio failure still leaves", test_player_play_audio_failure_still_leaves),
            ("wait exception still leaves", test_player_wait_for_playback_exception_still_leaves),
            ("wait returns False still leaves", test_player_wait_returns_false_still_leaves),
            ("leave_after=False never leaves", test_player_leave_after_false_never_leaves),
            ("leave_call failure does not propagate", test_player_leave_call_failure_does_not_propagate),
            ("storage key unique per call", test_player_storage_key_is_unique_per_call),
        ]),
        ("12D.3 RecallService", [
            ("play_audio posts correctly", test_recall_play_audio_posts_correctly),
            ("play_audio empty bytes raises", test_recall_play_audio_empty_bytes_raises),
            ("play_audio raises on error", test_recall_play_audio_raises_on_error_status),
            ("leave_call swallows exceptions", test_recall_leave_call_swallows_exceptions),
            ("wait_for_playback returns True on done", test_recall_wait_for_playback_returns_true_on_done),
            ("wait_for_playback returns False on failed", test_recall_wait_for_playback_returns_false_on_failed),
            ("wait_for_playback returns False on timeout", test_recall_wait_for_playback_returns_false_on_timeout),
            ("wait_for_playback no id falls back to sleep", test_recall_wait_for_playback_no_id_falls_back_to_sleep),
            ("wait_for_playback ignores other playback ids", test_recall_wait_for_playback_ignores_other_playback_ids),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 12D summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
