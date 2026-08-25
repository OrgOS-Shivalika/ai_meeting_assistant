"""capture_mode plumbing — the flag that decides whether voices get separated.

Stage 2 of SPEAKER_ATTRIBUTION_PLAN.md. What is guarded here:

  1. Online meetings must be UNCHANGED. `diarize` stays False unless a
     meeting explicitly asks for in-room capture, because turning it on for
     a normal call replaces exact roster names with anonymous "Speaker N".
  2. The flag must actually REACH the Recall payload. It is decided once,
     before the bot exists, and cannot be revisited — audio that was not
     analysed for distinct voices cannot be re-analysed from a transcript.
  3. A junk value must degrade to 'online', never 422 a meeting that is
     about to start.
  4. AssemblyAI cannot diarize. Asking it to must not raise (a rejected
     create_bot payload loses the meeting) but must not silently look
     supported either.

No DB and no network: the Recall payload is asserted by stubbing the HTTP
call, and everything else is a pure function.

Run: python tests/test_capture_mode.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.meeting_service import (  # noqa: E402
    VALID_CAPTURE_MODES, normalize_capture_mode,
)
from app.services.transcription.assemblyai_provider import AssemblyAIProvider  # noqa: E402
from app.services.transcription.deepgram_provider import DeepgramProvider  # noqa: E402


# ------------------------------------------------------- normalization


def test_valid_modes_pass_through():
    for mode in VALID_CAPTURE_MODES:
        assert normalize_capture_mode(mode) == mode, mode


def test_unknown_values_degrade_to_online():
    """Never 422 a meeting somebody is about to join. Guessing 'online'
    costs at worst today's behaviour; refusing costs the recording."""
    for junk in (None, "", "   ", "IN ROOM", "inroom", "room", 7, True, [], {}):
        assert normalize_capture_mode(junk) == "online", repr(junk)


def test_normalization_is_case_and_space_insensitive():
    assert normalize_capture_mode("  In_Room ") == "in_room"
    assert normalize_capture_mode("ONLINE") == "online"


# ----------------------------------------------------------- providers


def test_deepgram_diarize_defaults_off():
    """The whole online path depends on this default."""
    assert DeepgramProvider().build_recording_config("auto")["diarize"] is False


def test_deepgram_diarize_on_when_asked():
    cfg = DeepgramProvider().build_recording_config("auto", diarize=True)
    assert cfg["diarize"] is True, cfg


def test_deepgram_diarize_does_not_disturb_language():
    """Hindi/Hinglish handling must be unaffected by the new flag."""
    plain = DeepgramProvider().build_recording_config("hi")
    diarized = DeepgramProvider().build_recording_config("hi", diarize=True)
    assert plain["language"] == diarized["language"] == "hi"
    assert plain["model"] == diarized["model"]
    assert {k: v for k, v in plain.items() if k != "diarize"} == {
        k: v for k, v in diarized.items() if k != "diarize"
    }


def test_assemblyai_accepts_and_ignores_diarize():
    """Must not raise — a rejected payload loses the meeting."""
    before = AssemblyAIProvider().build_recording_config("auto")
    after = AssemblyAIProvider().build_recording_config("auto", diarize=True)
    assert before == after, (before, after)
    assert "diarize" not in after, after


def test_diarization_support_is_declared_not_inferred():
    """`create_bot` warns off this flag rather than matching on provider
    name, so a fourth provider cannot silently look in-room capable."""
    assert DeepgramProvider().supports_diarization is True
    assert AssemblyAIProvider().supports_diarization is False


# -------------------------------------------------- the Recall payload


def _captured_payload(capture_mode, provider):
    """Build a bot with the HTTP layer stubbed, returning the sent payload."""
    from app.services import recall_ai_service as ras

    sent = {}

    class _Resp:
        status_code = 201
        text = ""
        content = b"{}"

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "bot_stub"}

    def _fake_request(method, url, **kwargs):
        sent["method"] = method
        sent["url"] = url
        sent["json"] = kwargs.get("json")
        return _Resp()

    # `create_bot` does `from app.services.transcription import
    # get_active_provider` at CALL time, so the name must be patched on the
    # PACKAGE. Patching `registry.get_active_provider` does nothing: the
    # package `__init__` bound its own reference at import time. Without
    # pinning it here these tests would silently read whatever
    # TRANSCRIPTION_PROVIDER happens to be in .env.
    import app.services.transcription as transcription_pkg

    original_request = ras._request_with_retry
    original_get_active = transcription_pkg.get_active_provider
    try:
        ras._request_with_retry = _fake_request
        transcription_pkg.get_active_provider = lambda: provider

        service = ras.RecallService()
        service.base_url = "https://recall.test/api/v1"
        service.create_bot(
            "https://meet.google.com/abc-defg-hij", 4242,
            capture_mode=capture_mode,
        )
    finally:
        ras._request_with_retry = original_request
        transcription_pkg.get_active_provider = original_get_active

    return sent["json"]


def _provider_config(payload, provider):
    return payload["recording_config"]["transcript"]["provider"][
        provider.recall_provider_key
    ]


def test_online_meeting_sends_diarize_false():
    provider = DeepgramProvider()
    payload = _captured_payload("online", provider)
    assert _provider_config(payload, provider)["diarize"] is False, payload


def test_in_room_meeting_sends_diarize_true():
    """The flag has to survive all the way into the wire payload — this is
    the assertion that would have caught it being dropped in plumbing."""
    provider = DeepgramProvider()
    payload = _captured_payload("in_room", provider)
    assert _provider_config(payload, provider)["diarize"] is True, payload


def test_default_capture_mode_is_online():
    """A caller that never heard of capture_mode must get today's behaviour."""
    from app.services import recall_ai_service as ras
    import inspect

    default = inspect.signature(ras.RecallService.create_bot).parameters[
        "capture_mode"
    ].default
    assert default == "online", default


def test_junk_capture_mode_does_not_request_diarization():
    """`normalize_capture_mode` guards the DB write, but create_bot reads the
    column — so anything that is not exactly 'in_room' must stay off."""
    provider = DeepgramProvider()
    for junk in ("In_Room", "room", "", "true"):
        payload = _captured_payload(junk, provider)
        assert _provider_config(payload, provider)["diarize"] is False, junk


def test_in_room_on_assemblyai_does_not_raise():
    """Wrong provider for in-room is a WARNING, not a crash. Losing the bot
    is worse than a mono-speaker transcript."""
    provider = AssemblyAIProvider()
    payload = _captured_payload("in_room", provider)
    assert "diarize" not in _provider_config(payload, provider), payload


def test_in_room_disables_recalls_separate_streams_preference():
    """THE fix for meeting 4899.

    Recall runs its own diarization layer in front of the provider and defaults
    to `use_separate_streams_when_available: true` — attribute by
    per-participant audio stream. For a room sharing ONE account that resolves
    every utterance to one participant and throws the acoustic result away, so
    `diarize: true` on the provider did nothing and all 10 transcript blocks
    came back with no `speaker` field.
    """
    provider = DeepgramProvider()
    payload = _captured_payload("in_room", provider)
    diarization = payload["recording_config"]["transcript"].get("diarization")
    assert diarization == {
        "use_separate_streams_when_available": False
    }, payload["recording_config"]["transcript"]


def test_online_does_not_send_a_diarization_block():
    """Per-participant streams are exactly right for an ordinary call — that
    is what makes online attribution exact. Do not disturb Recall's default."""
    provider = DeepgramProvider()
    payload = _captured_payload("online", provider)
    assert "diarization" not in payload["recording_config"]["transcript"], payload


# ------------------------------------------- self-delivered webhook signing


def test_self_delivered_webhook_is_signed_and_verifies():
    """Meeting 4899 logged `401 Missing required headers` on this path, so the
    whole Phase 12E lost-webhook fallback was dead in any deployment with
    RECALL_WEBHOOK_SECRET set. Verify with the SAME svix call the endpoint
    uses, over the exact bytes posted."""
    from svix.webhooks import Webhook

    from app.services import recall_ai_service as ras

    secret = "whsec_" + "A" * 32
    original = ras.settings.RECALL_WEBHOOK_SECRET
    try:
        ras.settings.RECALL_WEBHOOK_SECRET = secret
        body, headers = ras._sign_webhook_payload(
            {"event": "bot.status_change", "data": {"status": {"code": "call_ended"}}}
        )
        assert "svix-id" in headers and "svix-signature" in headers, headers
        # Raises WebhookVerificationError if the signature does not match.
        Webhook(secret).verify(body.encode(), headers)
    finally:
        ras.settings.RECALL_WEBHOOK_SECRET = original


def test_self_delivered_webhook_unsigned_when_no_secret():
    """Local dev without a secret must keep working exactly as before."""
    from app.services import recall_ai_service as ras

    original = ras.settings.RECALL_WEBHOOK_SECRET
    try:
        ras.settings.RECALL_WEBHOOK_SECRET = None
        _, headers = ras._sign_webhook_payload({"event": "x"})
        assert "svix-id" not in headers, headers
    finally:
        ras.settings.RECALL_WEBHOOK_SECRET = original


def test_signed_body_is_posted_verbatim():
    """The signature covers exact bytes, so the body must not be
    re-serialized by requests (`data=`, never `json=`)."""
    import json as _json

    from app.services import recall_ai_service as ras

    payload = {"event": "bot.status_change", "data": {"status": {"code": "x"}}}
    body, _ = ras._sign_webhook_payload(payload)
    assert _json.loads(body) == payload
    assert isinstance(body, str)


def test_recording_config_shape_is_otherwise_untouched():
    """Everything Recall relies on must still be present."""
    provider = DeepgramProvider()
    payload = _captured_payload("in_room", provider)
    config = payload["recording_config"]
    assert "participant_events" in config, config
    assert config["meeting_metadata"]["capture_participant_list"] is True, config
    assert payload["meeting_url"].startswith("https://meet.google.com/"), payload


if __name__ == "__main__":
    checks = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for c in checks:
        try:
            c()
            print(f"  ok  {c.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {c.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {c.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)
