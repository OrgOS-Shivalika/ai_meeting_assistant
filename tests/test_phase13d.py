"""Phase 13D + 13E ship test - language-aware AI + bilingual wrap-up.

What this covers:

  13D.1 - Language detection helper
     - Pure English -> 'english'
     - Pure Hindi (Devanagari) -> 'hindi'
     - Mixed Hindi+English -> 'hinglish' OR 'hindi' based on ratio
     - Empty -> 'english' (safe default)

  13D.2 - Composer language-aware opening/closing templates
     - English state -> English opening/closing
     - Hindi state -> Hindi opening/closing (Devanagari)
     - Hinglish state -> Hinglish opening/closing

  13D.3 - Prompt template render() accepts target_language
     - target_language='hindi' includes Hindi few-shot guidance
     - Unknown language falls back to 'english'

  13D.4 - Composer passes detected language to render()
     - Hindi meeting state -> render() called with target_language='hindi'

  13E.1 - Hindi wrap-up patterns
     - 'धन्यवाद सबको' -> fires
     - 'फिर मिलेंगे' -> fires
     - 'मीटिंग खत्म' -> fires
     - 'ठीक है, चलते हैं' -> fires

  13E.2 - Hinglish wrap-up patterns
     - 'thik hai chaliye' -> fires
     - 'phir milenge' -> fires
     - 'shukriya everyone' -> fires
     - 'chaliye band karte hain' -> fires

  13E.3 - English regression (existing patterns still work)
     - 'thanks everyone' -> fires
     - 'see you all later' -> fires

  13E.4 - No false positives mid-meeting
     - 'धन्यवाद' alone (no group pronoun) -> no fire
     - 'अलविदा' alone -> no fire
     - 'thik hai' alone (no chalo/chaliye) -> no fire

Run with:

    venv\\Scripts\\python.exe tests\\test_phase13d.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, List, Tuple

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
# 13D.1 - Language detection
# ---------------------------------------------------------------------------

def test_detect_pure_english():
    from app.services.briefing.briefing_composer import _detect_language
    assert _detect_language("The team discussed sprint progress today.") == "english"


def test_detect_pure_hindi():
    from app.services.briefing.briefing_composer import _detect_language
    assert _detect_language("टीम ने आज स्प्रिंट की प्रगति पर चर्चा की।") == "hindi"


def test_detect_hinglish_mixed():
    from app.services.briefing.briefing_composer import _detect_language
    # Mostly English with some Hindi words inserted
    text = "The team ne sprint discuss kiya और कुछ नया भी सोचा।"
    result = _detect_language(text)
    # Should be either hinglish or hindi depending on ratio
    assert result in ("hinglish", "hindi"), f"unexpected {result!r}"


def test_detect_empty():
    from app.services.briefing.briefing_composer import _detect_language
    assert _detect_language("") == "english"
    assert _detect_language("   ") == "english"


def test_detect_hindi_with_some_english_brands():
    """Hindi sentence with a few English brand names should still detect as Hindi."""
    from app.services.briefing.briefing_composer import _detect_language
    text = "टीम ने Slack और Jira के साथ काम करने का निर्णय लिया।"
    # Heavy Devanagari with some English words — should resolve to hindi
    result = _detect_language(text)
    assert result == "hindi", f"unexpected {result!r}"


# ---------------------------------------------------------------------------
# 13D.2 - Composer language-aware opening/closing templates
# ---------------------------------------------------------------------------

class _FakeCC:
    def __init__(self, content: str):
        self.choices = [
            types.SimpleNamespace(message=types.SimpleNamespace(content=content))
        ]


class _FakeOpenAIClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: List[dict] = []
        client_self = self

        class _Chat:
            class _C:
                @staticmethod
                def create(**kwargs):
                    client_self.calls.append(kwargs)
                    i = min(len(client_self.calls) - 1, len(client_self.responses) - 1)
                    r = client_self.responses[i]
                    if isinstance(r, Exception):
                        raise r
                    return _FakeCC(r)

            completions = _C()

        self.chat = _Chat()


def _seed_meeting_state(meeting_id, *, summary, decisions, tasks):
    from app.services.meeting_memory.meeting_state_store import state_store
    from app.services.live_decisions.live_decision_models import LiveDecision
    from app.services.live_tasks.live_task_models import LiveTask
    state = state_store.get_state(meeting_id)
    state.active_decisions = {}
    state.active_tasks = {}
    state.summary = summary
    for i, d in enumerate(decisions):
        dec = LiveDecision(
            id=f"d{i}", decision=d["decision"], fingerprint=f"fpd{i}",
            decided_by=d.get("decided_by"), decision_type="other",
            status="confirmed", confidence=0.9, source_speaker="X",
            source_transcript_chunk_id=1,
        )
        state.active_decisions[dec.fingerprint] = dec
    for i, t in enumerate(tasks):
        task = LiveTask(
            id=f"t{i}", task=t["task"], fingerprint=f"fpt{i}",
            owner=t.get("owner"),
            ownership_type="explicit" if t.get("owner") else "unresolved",
            status="confirmed", confidence=0.9, source_speaker="X",
            source_transcript_chunk_id=1, deadline=t.get("deadline"),
        )
        state.active_tasks[task.fingerprint] = task


def _wipe(meeting_id):
    from app.services.meeting_memory.meeting_state_store import state_store
    state_store.remove_state(meeting_id)


def test_composer_english_state_uses_english_templates():
    from app.services.briefing.briefing_composer import (
        BriefingComposer, _OPENING_TEMPLATES, _CLOSING_TEMPLATES,
    )
    mid = f"test-{uuid.uuid4()}"
    _seed_meeting_state(
        mid,
        summary="The team discussed sprint progress and the API migration.",
        decisions=[{"decision": "Migrate auth first", "decided_by": "Alice"}],
        tasks=[{"task": "Prepare doc by Friday", "owner": "Bob"}],
    )

    response = json.dumps({
        "summary_text": "The team made progress on multiple fronts and reviewed migrations.",
        "decisions_text": "One decision was made today about auth migration.",
        "assigned_text": "Bob will prepare the doc by Friday.",
        "unassigned_text": "",
    })
    composer = BriefingComposer()
    composer._client_factory = staticmethod(lambda: _FakeOpenAIClient([response]))
    try:
        script = composer.compose(meeting_id=mid)
        assert script is not None
        assert script.opening_text == _OPENING_TEMPLATES["english"]
        assert script.closing_text == _CLOSING_TEMPLATES["english"]
    finally:
        _wipe(mid)


def test_composer_hindi_state_uses_hindi_templates():
    """Phase 13D-revised: language detection now reads the RAW
    transcript from the DB (not the now-English summary). We use the
    composer's `_read_raw_transcript` patched to return Hindi text."""
    from app.services.briefing.briefing_composer import (
        BriefingComposer, _OPENING_TEMPLATES, _CLOSING_TEMPLATES,
    )
    mid = f"test-{uuid.uuid4()}"
    # The state's summary/decisions/tasks are now ENGLISH (per the
    # revised policy). The Hindi signal comes from the raw transcript.
    _seed_meeting_state(
        mid,
        summary="The team discussed sprint progress and API migration.",
        decisions=[{"decision": "Migrate auth first", "decided_by": "Ravi"}],
        tasks=[{"task": "Prepare doc by Friday", "owner": "Sahil"}],
    )

    response = json.dumps({
        "summary_text": "टीम ने आज प्रगति की समीक्षा की।",
        "decisions_text": "आज एक निर्णय लिया गया कि ऑथ पहले माइग्रेट करेंगे।",
        "assigned_text": "साहिल शुक्रवार तक डॉक तैयार करेगा।",
        "unassigned_text": "",
    })
    composer = BriefingComposer()
    composer._client_factory = staticmethod(lambda: _FakeOpenAIClient([response]))
    # Patch the DB reader to simulate a Hindi raw transcript
    composer._read_raw_transcript = lambda mid_: (
        "रवि: हम API माइग्रेट करेंगे। साहिल शुक्रवार तक डॉक तैयार करेगा।"
    )
    try:
        script = composer.compose(meeting_id=mid)
        assert script is not None
        assert script.opening_text == _OPENING_TEMPLATES["hindi"]
        assert script.closing_text == _CLOSING_TEMPLATES["hindi"]
        # full_text should start with Devanagari opening
        assert script.full_text.startswith("मीटिंग")
    finally:
        _wipe(mid)


# ---------------------------------------------------------------------------
# 13D.3 - Prompt template render() with target_language
# ---------------------------------------------------------------------------

def test_render_accepts_target_language():
    from app.ai_agents.prompts.closing_briefing_prompt import render
    text = render(
        max_words=100,
        summary="The team discussed migrations.",
        decisions=[],
        assigned_tasks=[],
        unassigned_tasks=[],
        target_language="hindi",
    )
    assert "TARGET LANGUAGE" in text or "target_language" in text or "hindi" in text


def test_render_unknown_language_falls_back_to_english():
    from app.ai_agents.prompts.closing_briefing_prompt import render
    text = render(
        max_words=100,
        summary="Discussion.",
        decisions=[],
        assigned_tasks=[],
        unassigned_tasks=[],
        target_language="klingon",  # invalid
    )
    # Should not raise and should contain 'english' as the resolved target
    assert "english" in text.lower()


# ---------------------------------------------------------------------------
# 13D.4 - Composer passes detected language to render()
# ---------------------------------------------------------------------------

def test_composer_passes_detected_language_to_prompt():
    """Phase 13D-revised: when the raw transcript is Hindi-heavy,
    target_language='hindi' should be in the user prompt — even though
    the summary/decisions in state are English."""
    from app.services.briefing.briefing_composer import BriefingComposer

    mid = f"test-{uuid.uuid4()}"
    # State outputs are now ALWAYS English per the revised policy
    _seed_meeting_state(
        mid,
        summary="The team discussed sprint progress and the API migration decision.",
        decisions=[{"decision": "Migrate auth first", "decided_by": "Ravi"}],
        tasks=[],
    )

    response = json.dumps({
        "summary_text": "टीम ने प्रगति की समीक्षा की।",
        "decisions_text": "एक निर्णय लिया गया।",
        "assigned_text": "",
        "unassigned_text": "",
    })
    client = _FakeOpenAIClient([response])
    composer = BriefingComposer()
    composer._client_factory = staticmethod(lambda: client)
    # Hindi RAW transcript — drives language detection
    composer._read_raw_transcript = lambda mid_: (
        "रवि: हम सबसे पहले ऑथ सर्विस को माइग्रेट करेंगे।"
    )
    try:
        composer.compose(meeting_id=mid)
        # Check the user prompt sent to the LLM
        assert len(client.calls) >= 1
        user_prompt = client.calls[0]["messages"][-1]["content"]
        assert "hindi" in user_prompt.lower(), (
            "expected 'hindi' target_language in the prompt"
        )
    finally:
        _wipe(mid)


# ---------------------------------------------------------------------------
# 13D.5 - Composer reads raw transcript (not state summary) for language
# ---------------------------------------------------------------------------

def test_composer_detects_english_when_raw_transcript_is_english():
    """English raw transcript -> English templates, even when state
    happens to contain Devanagari (e.g. owner names)."""
    from app.services.briefing.briefing_composer import (
        BriefingComposer, _OPENING_TEMPLATES,
    )
    mid = f"test-{uuid.uuid4()}"
    _seed_meeting_state(
        mid,
        summary="The team discussed sprint progress.",
        decisions=[{"decision": "Migrate auth first", "decided_by": "रवि"}],
        tasks=[],
    )
    response = json.dumps({
        "summary_text": "The team made decisions about migration.",
        "decisions_text": "One decision was made today.",
        "assigned_text": "",
        "unassigned_text": "",
    })
    composer = BriefingComposer()
    composer._client_factory = staticmethod(lambda: _FakeOpenAIClient([response]))
    composer._read_raw_transcript = lambda mid_: (
        "Ravi: Let's migrate the auth service first. Sahil will prepare the doc."
    )
    try:
        script = composer.compose(meeting_id=mid)
        assert script is not None
        assert script.opening_text == _OPENING_TEMPLATES["english"]
    finally:
        _wipe(mid)


def test_composer_falls_back_to_english_when_no_raw_transcript():
    """If the transcript column is empty (e.g. provider-failure
    meetings before the live-fallback fix), compose with English."""
    from app.services.briefing.briefing_composer import (
        BriefingComposer, _OPENING_TEMPLATES,
    )
    mid = f"test-{uuid.uuid4()}"
    _seed_meeting_state(
        mid,
        summary="The team made progress.",
        decisions=[{"decision": "Ship X", "decided_by": "Y"}],
        tasks=[],
    )
    response = json.dumps({
        "summary_text": "Progress was made.",
        "decisions_text": "One decision was made.",
        "assigned_text": "",
        "unassigned_text": "",
    })
    composer = BriefingComposer()
    composer._client_factory = staticmethod(lambda: _FakeOpenAIClient([response]))
    composer._read_raw_transcript = lambda mid_: None  # no transcript
    try:
        script = composer.compose(meeting_id=mid)
        assert script is not None
        assert script.opening_text == _OPENING_TEMPLATES["english"]
    finally:
        _wipe(mid)


# ---------------------------------------------------------------------------
# 13E.1 - Hindi wrap-up patterns
# ---------------------------------------------------------------------------

def _capture_bus():
    from app.services.live_events import event_bus as bus_mod
    captured = []
    orig_broadcast = bus_mod.live_event_bus._broadcast_to_ui
    orig_subs = list(bus_mod.live_event_bus._subscribers)
    bus_mod.live_event_bus._subscribers = []
    bus_mod.live_event_bus._broadcast_to_ui = lambda e: captured.append(e)

    def restore():
        bus_mod.live_event_bus._broadcast_to_ui = orig_broadcast
        bus_mod.live_event_bus._subscribers = orig_subs

    return captured, restore


def _events_of(captured, event_type):
    return [e for e in captured if e.event_type == event_type]


def _assert_fires(phrase):
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"hi-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, phrase)
        wd = _events_of(captured, "meeting.winding_down")
        assert len(wd) == 1, f"phrase did NOT fire: {phrase!r}"
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


def _assert_does_not_fire(phrase):
    from app.services.live_stream import meeting_lifecycle as lm
    mid = f"hi-{uuid.uuid4()}"
    lm.meeting_lifecycle_monitor.reset(mid)
    captured, restore = _capture_bus()
    original_grace = lm._LINGUISTIC_GRACE_S
    lm._LINGUISTIC_GRACE_S = 0
    try:
        lm.meeting_lifecycle_monitor.on_transcript_text(mid, phrase)
        wd = _events_of(captured, "meeting.winding_down")
        assert wd == [], f"phrase falsely fired: {phrase!r}"
    finally:
        lm._LINGUISTIC_GRACE_S = original_grace
        restore()


def test_hindi_thanks_everyone_fires():
    _assert_fires("ठीक है, धन्यवाद सबको, फिर मिलेंगे।")


def test_hindi_phir_milenge_fires():
    _assert_fires("फिर मिलेंगे अगले हफ्ते।")


def test_hindi_meeting_khatam_fires():
    _assert_fires("मीटिंग खत्म, सब लोग धन्यवाद।")


def test_hindi_thik_hai_chalte_hain_fires():
    _assert_fires("ठीक है, चलते हैं अब।")


def test_hindi_bas_itna_hi_fires():
    _assert_fires("बस इतना ही आज के लिए।")


def test_hindi_shubh_din_fires():
    _assert_fires("अच्छा दिन हो सबको।")


# ---------------------------------------------------------------------------
# 13E.2 - Hinglish wrap-up patterns
# ---------------------------------------------------------------------------

def test_hinglish_thik_hai_chaliye_fires():
    _assert_fires("OK thik hai chaliye, band karte hain.")


def test_hinglish_phir_milenge_fires():
    _assert_fires("Phir milenge next week.")


def test_hinglish_shukriya_everyone_fires():
    _assert_fires("Shukriya everyone, see you tomorrow.")


def test_hinglish_chaliye_band_karte_hain_fires():
    _assert_fires("Chaliye band karte hain ab.")


def test_hinglish_dhanyawad_sab_fires():
    _assert_fires("Dhanyawad sabko for joining.")


def test_hinglish_alvida_sab_fires():
    _assert_fires("Alvida sab, take care.")


# ---------------------------------------------------------------------------
# 13E.3 - English regression
# ---------------------------------------------------------------------------

def test_english_thanks_everyone_still_fires():
    _assert_fires("Thanks everyone, see you tomorrow.")


def test_english_see_you_later_still_fires():
    _assert_fires("Cool, see you all later.")


def test_english_thats_a_wrap_still_fires():
    _assert_fires("Alright that's a wrap.")


# ---------------------------------------------------------------------------
# 13E.4 - Hindi no false positives
# ---------------------------------------------------------------------------

def test_hindi_solo_dhanyawad_no_fire():
    """'धन्यवाद' alone (no group pronoun) is too generic — used as
    "thanks" in everyday phrases."""
    _assert_does_not_fire("रवि का धन्यवाद इस काम के लिए।")


def test_hindi_solo_alvida_no_fire():
    """'अलविदा' alone is OK in references."""
    _assert_does_not_fire("उसने अलविदा कहा और चला गया।")


def test_hinglish_solo_thik_hai_no_fire():
    """'thik hai' alone is the most common Hindi filler word."""
    _assert_does_not_fire("Thik hai, that works for me.")


def test_hindi_mid_meeting_phir_milte_hain_no_fire():
    """'मिलते हैं' alone without a day reference shouldn't fire —
    requires kal/agle/etc."""
    _assert_does_not_fire("उससे फिर मिलते हैं इस पर चर्चा करने के लिए।")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    suites = [
        ("13D.1 language detection", [
            ("pure English -> english", test_detect_pure_english),
            ("pure Hindi -> hindi", test_detect_pure_hindi),
            ("Hinglish mixed", test_detect_hinglish_mixed),
            ("empty -> english", test_detect_empty),
            ("Hindi with English brands -> hindi", test_detect_hindi_with_some_english_brands),
        ]),
        ("13D.2 composer templates", [
            ("English state -> English opening/closing", test_composer_english_state_uses_english_templates),
            ("Hindi state -> Hindi opening/closing", test_composer_hindi_state_uses_hindi_templates),
        ]),
        ("13D.3 render() target_language", [
            ("accepts target_language", test_render_accepts_target_language),
            ("unknown language falls back to english", test_render_unknown_language_falls_back_to_english),
        ]),
        ("13D.4 composer -> render integration", [
            ("Hindi raw transcript -> render gets target='hindi'", test_composer_passes_detected_language_to_prompt),
        ]),
        ("13D.5 raw-transcript language detection", [
            ("English raw transcript -> English templates", test_composer_detects_english_when_raw_transcript_is_english),
            ("Missing transcript falls back to English", test_composer_falls_back_to_english_when_no_raw_transcript),
        ]),
        ("13E.1 Hindi wrap-up patterns", [
            ("dhanyawad sabko", test_hindi_thanks_everyone_fires),
            ("phir milenge", test_hindi_phir_milenge_fires),
            ("meeting khatam", test_hindi_meeting_khatam_fires),
            ("thik hai chalte hain", test_hindi_thik_hai_chalte_hain_fires),
            ("bas itna hi", test_hindi_bas_itna_hi_fires),
            ("shubh din", test_hindi_shubh_din_fires),
        ]),
        ("13E.2 Hinglish patterns", [
            ("thik hai chaliye band", test_hinglish_thik_hai_chaliye_fires),
            ("phir milenge", test_hinglish_phir_milenge_fires),
            ("shukriya everyone", test_hinglish_shukriya_everyone_fires),
            ("chaliye band karte hain", test_hinglish_chaliye_band_karte_hain_fires),
            ("dhanyawad sabko", test_hinglish_dhanyawad_sab_fires),
            ("alvida sab", test_hinglish_alvida_sab_fires),
        ]),
        ("13E.3 English regression", [
            ("thanks everyone", test_english_thanks_everyone_still_fires),
            ("see you all later", test_english_see_you_later_still_fires),
            ("that's a wrap", test_english_thats_a_wrap_still_fires),
        ]),
        ("13E.4 no false positives", [
            ("solo dhanyawad no fire", test_hindi_solo_dhanyawad_no_fire),
            ("solo alvida no fire", test_hindi_solo_alvida_no_fire),
            ("solo thik hai no fire", test_hinglish_solo_thik_hai_no_fire),
            ("mid-meeting 'milte hain' no fire", test_hindi_mid_meeting_phir_milte_hain_no_fire),
        ]),
    ]

    for label, cases in suites:
        with section(label):
            for name, fn in cases:
                check(label.split()[0], name, fn)

    print()
    print("=== Phase 13D+E summary ===")
    passes = sum(1 for r in results if r[2] == "PASS")
    fails = sum(1 for r in results if r[2] == "FAIL")
    print(f"  PASS: {passes}")
    print(f"  FAIL: {fails}")
    print(f"  total: {len(results)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
