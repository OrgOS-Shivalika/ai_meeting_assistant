"""Realtime diarization-label extraction — where Recall actually puts it.

Two in-room test meetings (4899, 4903) came back with every utterance on one
speaker even though the bot config was correct. Cause: this code only looked at
`source["speaker"]` / `data_block["speaker"]`, but per
https://docs.recall.ai/docs/diarization machine diarization emits the label in
`transcript.provider_data`.

Recall's docs do not name the key inside `provider_data`, so `_diarization_label`
searches the plausible shapes and `process_transcript_event` dumps the real one
once per meeting when it finds nothing. These tests pin the shapes we DO know,
and pin the guards that stop junk becoming a speaker.

Run: python tests/test_realtime_diarization.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.webhooks.recall_webhook import (  # noqa: E402
    _clean_dia_label, _diarization_label, extract_transcript_fields,
    label_in_provider_payload,
)


def _event(*, provider_data=None, source_extra=None, data_extra=None):
    """A realtime transcript.data payload in Recall's nested shape."""
    source = {
        "participant": {"id": 100, "name": "Divyansh Bhardwaj"},
        "words": [{"text": "hello"}, {"text": "there"}],
        "is_final": True,
    }
    if source_extra:
        source.update(source_extra)
    data = {"data": {"transcript": source}}
    if provider_data is not None:
        data["provider_data"] = provider_data
    if data_extra:
        data.update(data_extra)
    return {"event": "transcript.data", "data": data}


# ------------------------------------------------- provider_data locations


def test_label_read_from_provider_data_speaker():
    """The documented location for machine diarization."""
    payload = _event(provider_data={"speaker": 2})
    assert _diarization_label(
        payload["data"]["data"]["transcript"], payload["data"],
    ) == 2


def test_label_read_from_deepgram_streaming_shape():
    """In case provider_data forwards Deepgram's response fragment verbatim:
    channel.alternatives[0].words[].speaker"""
    payload = _event(provider_data={
        "channel": {"alternatives": [{"words": [
            {"word": "hello", "speaker": 1},
            {"word": "there", "speaker": 1},
        ]}]}
    })
    assert _diarization_label(
        payload["data"]["data"]["transcript"], payload["data"],
    ) == 1


def test_label_read_from_flat_provider_data_words():
    payload = _event(provider_data={"words": [{"speaker": 3}]})
    assert _diarization_label(
        payload["data"]["data"]["transcript"], payload["data"],
    ) == 3


def test_legacy_flat_location_still_works():
    """The pre-fix location. Costs nothing to keep and covers a provider that
    does surface the label there."""
    payload = _event(source_extra={"speaker": 4})
    assert _diarization_label(
        payload["data"]["data"]["transcript"], payload["data"],
    ) == 4


def test_provider_data_wins_over_flat():
    """provider_data is the documented location, so it is searched first."""
    payload = _event(provider_data={"speaker": 7}, source_extra={"speaker": 9})
    assert _diarization_label(
        payload["data"]["data"]["transcript"], payload["data"],
    ) == 7


def test_absent_label_is_none():
    payload = _event()
    assert _diarization_label(
        payload["data"]["data"]["transcript"], payload["data"],
    ) is None


# ------------------------------- transcript.provider_data (its own event)
#
# The label lives ONLY on this event. `transcript.data` is participant-shaped
# with no slot for one — which is why in-room meetings 4899/4903/4905 all showed
# a single speaker despite a correct bot config: we never subscribed to it.


def test_provider_payload_shapes_all_resolve():
    """Recall documents the structure as "varies by provider", so the plausible
    Deepgram layouts are all accepted."""
    cases = {
        "channel.alternatives":
            ({"channel": {"alternatives": [{"words": [{"speaker": 2}]}]}}, 2),
        "flat alternatives":
            ({"alternatives": [{"words": [{"speaker": 3}]}]}, 3),
        "flat words":
            ({"words": [{"speaker": 4}]}, 4),
        "top-level speaker":
            ({"speaker": "B"}, "B"),
        "speaker_label":
            ({"speaker_label": 6}, 6),
        "nothing":
            ({"words": [{"word": "hi"}]}, None),
    }
    for name, (payload, expected) in cases.items():
        assert label_in_provider_payload(payload) == expected, name


def test_provider_payload_ignores_non_dicts():
    for junk in (None, [], "x", 3):
        assert label_in_provider_payload(junk) is None, repr(junk)


def test_provider_data_event_is_routed_separately():
    """`process_transcript_event` early-returns on anything that is not
    transcript.data / transcript.partial_data, so the generic
    `"transcript" in event` branch would have swallowed this event."""
    import inspect

    from app.api.webhooks import recall_webhook as rw

    source = inspect.getsource(rw.handle_recall_webhook)
    assert 'if event == "transcript.provider_data":' in source, source
    # The generic branch must be SUBORDINATE to the specific one. Asserting on
    # `elif` rather than comparing string positions, because the surrounding
    # comment also mentions `"transcript" in event` and a positional check
    # matches the comment instead of the code.
    assert 'elif "transcript" in event:' in source, (
        "the generic transcript branch must be an elif under the "
        "provider_data check, or it will swallow the event"
    )


def test_provider_data_subscribed_for_in_room_only():
    """A second raw stream is worth it for a room; online gets exact
    attribution from the roster without it."""
    import app.services.recall_ai_service as ras
    import app.services.transcription as tpkg
    from app.services.transcription.deepgram_provider import DeepgramProvider

    class _Resp:
        status_code = 201
        text = ""
        content = b"{}"

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "bot"}

    def _events_for(mode):
        sent = {}
        orig_req, orig_prov = ras._request_with_retry, tpkg.get_active_provider
        try:
            ras._request_with_retry = (
                lambda m, u, **k: (sent.update(k.get("json") or {}), _Resp())[1]
            )
            tpkg.get_active_provider = lambda: DeepgramProvider()
            service = ras.RecallService()
            service.base_url = "https://recall.test/api/v1"
            service.create_bot(
                "https://meet.google.com/abc-defg-hij", 1, capture_mode=mode,
            )
        finally:
            ras._request_with_retry, tpkg.get_active_provider = orig_req, orig_prov
        endpoints = sent["recording_config"]["realtime_endpoints"]
        return endpoints[0]["events"]

    assert "transcript.provider_data" in _events_for("in_room")
    assert "transcript.provider_data" not in _events_for("online")


# ----------------------------------------------------------------- guards


def test_label_zero_is_not_dropped():
    """Truthiness on an int has bitten this codebase repeatedly."""
    assert _clean_dia_label(0) == 0


def test_booleans_are_never_labels():
    """`bool` subclasses `int`, and `diarize: true` sits one field away in the
    provider config."""
    assert _clean_dia_label(True) is None
    assert _clean_dia_label(False) is None


def test_letter_labels_are_accepted():
    """Recall's docs: labels "like `A`, `B`, `C` or `0`, `1`, `2`"."""
    assert _clean_dia_label("A") == "A"
    assert _clean_dia_label("  B ") == "B"


def test_digit_strings_normalize_to_int():
    """Otherwise "0" and 0 would become two different speakers."""
    assert _clean_dia_label("0") == 0
    assert _clean_dia_label("12") == 12


def test_a_sentence_is_never_a_label():
    """Guards against a provider reusing the key for something else."""
    for junk in ("Divyansh Bhardwaj", "hello there everyone", "", "   ", None,
                 {"a": 1}, [1], 3.5):
        assert _clean_dia_label(junk) is None, repr(junk)


# ------------------------------------------------- end-to-end extraction


def test_extract_transcript_fields_returns_the_label():
    payload = _event(provider_data={"speaker": 1})
    speaker, text, is_final, p_id, dia = extract_transcript_fields(
        payload, "transcript.data",
    )
    assert dia == 1, dia
    assert p_id == 100 and speaker == "Divyansh Bhardwaj"
    assert text == "hello there" and is_final is True


def test_roster_name_and_label_stay_separate():
    """The name is a string from the platform roster; the label is an acoustic
    index. Conflating them once crashed on `(1).strip()`."""
    payload = _event(provider_data={"speaker": 2})
    speaker, _, _, p_id, dia = extract_transcript_fields(
        payload, "transcript.data",
    )
    assert isinstance(speaker, str) and isinstance(dia, int)
    assert speaker != dia


def test_in_room_labels_separate_voices_end_to_end():
    """Three utterances, one account, three labels -> three live speakers."""
    from app.processors.transcript_processor import TranscriptProcessor as TP

    seen = {}
    labels = []
    for dia in (0, 1, 2, 0):
        payload = _event(provider_data={"speaker": dia})
        _, _, _, p_id, got = extract_transcript_fields(payload, "transcript.data")
        labels.append(TP.incremental_speaker_label(
            p_id, "Divyansh Bhardwaj", seen, dia_speaker=got,
            capture_mode="in_room",
        ))
    assert labels == ["Speaker 0", "Speaker 1", "Speaker 2", "Speaker 0"], labels


def test_online_ignores_the_label_even_when_present():
    """A misconfigured online meeting must not fragment a named participant."""
    from app.processors.transcript_processor import TranscriptProcessor as TP

    seen = {}
    out = []
    for dia in (0, 1):
        payload = _event(provider_data={"speaker": dia})
        _, _, _, p_id, got = extract_transcript_fields(payload, "transcript.data")
        out.append(TP.incremental_speaker_label(
            p_id, "Asha", seen, dia_speaker=got, capture_mode="online",
        ))
    assert out == ["Asha", "Asha"], out


def test_speaker_zero_survives_the_provider_data_handler():
    """Label 0 must not be swallowed by a truthiness test.

    `label_in_provider_payload` returns the label itself, and diarization
    labels start at ZERO — so `a or b` discards a perfectly good 0 and falls
    through to whatever b is. `process_provider_data_event` had exactly that,
    which meant the FIRST speaker in every room (the commonest label there is)
    was recorded as "no label found": `"label": null` in
    .cache/diarization_samples.jsonl and `label=None` in the log, while
    diarization was in fact working.

    That handler is the instrument we read the in-room experiment off, so a
    false negative there is worse than a plain bug — it would have condemned a
    working setup. Asserted on 0 specifically; every other label is truthy and
    would have passed either way.
    """
    import asyncio
    import app.api.webhooks.recall_webhook as wh

    payload = {
        "event": "transcript.provider_data",
        "data": {"data": {"channel": {"alternatives": [
            {"words": [{"text": "hello", "speaker": 0}]}
        ]}}},
    }

    # The probe the handler runs, in the handler's own shape.
    block = payload["data"]
    inner = block["data"]
    direct = wh.label_in_provider_payload(inner)
    assert direct == 0, f"extractor itself should find 0, got {direct!r}"
    assert not direct, "precondition: 0 is falsy — that is the whole trap"

    # Now the handler end to end, reading back what it actually recorded.
    # Redirect the sample path rather than stubbing `open`: the handler writes
    # through the builtin, and this also exercises the real makedirs/append.
    import json as _json
    import tempfile

    meeting_id = 999_001
    original_path = wh._DIA_SAMPLE_PATH
    tmp = os.path.join(tempfile.mkdtemp(prefix="dia_test_"), "samples.jsonl")
    wh._DIA_SAMPLE_PATH = tmp
    wh._DIA_SAMPLES_WRITTEN.pop(meeting_id, None)
    try:
        asyncio.run(wh.process_provider_data_event(meeting_id, payload))
        assert os.path.exists(tmp), "handler wrote no sample file at all"
        lines = [l for l in open(tmp, encoding="utf-8").read().splitlines() if l.strip()]
        assert lines, "sample file is empty"
        record = _json.loads(lines[0])
    finally:
        wh._DIA_SAMPLE_PATH = original_path
        wh._DIA_SAMPLES_WRITTEN.pop(meeting_id, None)
        try:
            os.remove(tmp)
            os.rmdir(os.path.dirname(tmp))
        except OSError:
            pass

    assert record["label"] == 0, (
        f"handler recorded label={record['label']!r}; speaker 0 was swallowed"
    )


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
