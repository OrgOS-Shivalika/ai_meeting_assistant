import re
from app.utils.admin_enums import CaptureMode
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Label for a speaker Recall identified but never named. Recall routinely
# sends {"id": 101, "name": null} for dial-ins, guests, and anyone whose
# platform profile it cannot read — 71 of the stored meetings contain at
# least one. The ID is still a reliable identity, so we show that.
UNNAMED_SPEAKER_PREFIX = "Participant"

_FALLBACK_SPEAKER = "Unknown Speaker"


class TranscriptProcessor:

    @staticmethod
    def clean_text(text: str) -> str:
        text = re.sub(r"\s+([.,!?])", r"\1", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Speaker labelling
    #
    # ONE rule underpins both helpers: the participant ID is the identity,
    # the name is only a display label. Every attribution bug found in this
    # area came from treating the name as the key:
    #
    #   - Recall assigns DIFFERENT ids to two people who share a name
    #     (meeting 4421: ids 100 and 200 are both "Divyansh Bhardwaj").
    #     Keying on the name merged them into one speaker.
    #   - Recall sends name=null for unidentified participants, and
    #     `participant.get("name", "Unknown")` does NOT catch that — the
    #     key is present with a null value, so the default never fires and
    #     the literal string "None" became the speaker.
    # ------------------------------------------------------------------

    @staticmethod
    def build_speaker_labels(pairs) -> dict:
        """Map every participant id to a unique display label.

        `pairs` is an ordered iterable of (participant_id, name); the first
        appearance of an id wins, and duplicate names are numbered in that
        same first-appearance order so the numbering is deterministic.

        Use this when the whole conversation is in hand. A streaming caller
        cannot — see :meth:`incremental_speaker_label`.
        """
        base: dict = {}
        for p_id, name in pairs:
            # `is None`, not truthiness: Recall numbers participants from 0
            # on some platforms and `if p_id:` silently dropped that speaker.
            if p_id is None:
                continue
            if p_id not in base:
                base[p_id] = (name or "").strip()

        by_name: dict = {}
        for p_id, name in base.items():
            by_name.setdefault(name, []).append(p_id)

        labels: dict = {}
        for name, ids in by_name.items():
            if not name:
                # Nameless: the id IS the only identity we have, so every
                # one of these is distinct. Never collapse them together.
                for p_id in ids:
                    labels[p_id] = f"{UNNAMED_SPEAKER_PREFIX} {p_id}"
            elif len(ids) == 1:
                labels[ids[0]] = name
            else:
                for i, p_id in enumerate(ids, 1):
                    labels[p_id] = f"{name} ({i})"
        return labels

    @staticmethod
    def incremental_speaker_label(
        p_id, name, seen: dict, dia_speaker=None,
        *, capture_mode: str = CaptureMode.ONLINE.value,
    ) -> str:
        """Label one speaker when the rest of the conversation isn't known yet.

        `seen` is a per-meeting {participant_id: label} map the caller owns
        and mutates. It exists because the live path handles one utterance
        at a time and cannot rewrite lines already sent to the browser.

        Consequence, deliberate and documented: when a second person shares
        a name, the first keeps the bare name and the second becomes
        "Name (2)" — whereas the batch pass, which sees everything, yields
        "Name (1)" and "Name (2)". Both are unambiguous. Making them
        identical would mean buffering the live transcript until the meeting
        ended, which defeats the point of a live transcript.
        """
        # `isinstance` guard, not just `or ""`: a caller that hands us a
        # diarization INDEX where a name belongs would otherwise reach
        # `.strip()` on an int and raise. Names are strings, always.
        real = name.strip() if isinstance(name, str) else ""

        # Identity precedence. `capture_mode` is the tiebreaker for the ONE
        # conflict this cannot resolve alone: the roster says "one person",
        # diarization says "several voices".
        #
        #   ONLINE, name present   -> roster wins outright, diarization index
        #                             ignored. The roster is exact; diarization
        #                             is a guess, and letting a guess split one
        #                             named participant would render them as
        #                             "Asha" and "Asha (2)".
        #   IN_ROOM, dia present   -> the index wins EVEN IF a name exists.
        #                             This is the whole fix. A laptop in a room
        #                             joins under one account that DOES carry a
        #                             name — often not even a person's
        #                             ("Conference Room 2") — so the name
        #                             belongs to the account, not the speaker.
        #                             Before this branch, `real` was truthy and
        #                             the index was discarded, so turning
        #                             diarization on changed nothing at all.
        #   no name + dia          -> the pre-existing in-room case (dial-ins,
        #                             profiles Recall cannot read). Unchanged.
        #   neither                -> the participant id alone.
        in_room = CaptureMode.coerce(capture_mode) is CaptureMode.IN_ROOM
        if dia_speaker is not None and (in_room or not real):
            key = ("d", p_id, dia_speaker)
        elif real:
            key = ("p", p_id)
        elif p_id is not None:
            key = ("p", p_id)
        else:
            return _FALLBACK_SPEAKER

        if key in seen:
            return seen[key]

        # Branch on the KEY SHAPE, not on `real` again. The key already
        # encodes the precedence decision above, and re-deriving it from
        # `real` here would silently undo it: an in-room cluster whose account
        # happens to be named would take the roster label, so all three
        # clusters would render as the same name and the split would be
        # invisible.
        if key[0] == "d":
            # Anonymous by nature — diarization separates voices, it does
            # not identify them. Naming these is the job of the mapping
            # ladder (roll-call / enrollment / manual reassignment), which
            # runs on the batch pass where the whole meeting is in hand.
            label = f"Speaker {dia_speaker}"
        elif real:
            # How many OTHER ids already claim this same base name?
            taken = sum(
                1 for other in seen.values()
                if other == real or other.startswith(f"{real} (")
            )
            label = real if taken == 0 else f"{real} ({taken + 1})"
        else:
            label = f"{UNNAMED_SPEAKER_PREFIX} {p_id}"

        seen[key] = label
        return label

    @staticmethod
    def format(
        transcript_json: list,
        *,
        capture_mode: str = CaptureMode.ONLINE.value,
        calendar_attendees=None,
    ) -> str:
        """Compiled transcript -> the flat "Speaker: text" string.

        THE chokepoint. Every downstream consumer — the World-A analyzer,
        agents_v2, Continuum, chunking, embedding, memory distillation, tasks,
        the closing briefing — reads this string and nothing else, which is why
        in-room attribution is fixed here instead of in a parallel pipeline.

        `capture_mode` decides which of two routes runs; see
        :meth:`format_detailed`. Defaults to ONLINE so every existing caller
        keeps its exact behaviour.
        """
        text, _, _ = TranscriptProcessor.format_detailed(
            transcript_json,
            capture_mode=capture_mode,
            calendar_attendees=calendar_attendees,
        )
        return text

    @staticmethod
    def format_detailed(
        transcript_json: list,
        *,
        capture_mode: str = CaptureMode.ONLINE.value,
        calendar_attendees=None,
    ):
        """Same as :meth:`format` but also returns what it learned.

        Returns ``(text, resolutions, diagnostics)``. The extras are ``{}`` and
        ``None`` on the online route, which has nothing to resolve. They exist
        so the pipeline can persist `label_mappings` and act on the
        under-clustering flag without deriving turns a second time.

        Two routes, and the split is deliberate:

        ONLINE — the pre-existing code path, character for character. It is not
        merely equivalent, it is the same function. Online attribution works
        today and there is no requirement to change it, so it does not go
        through turn derivation at all and stays byte-identical. (Turn merging
        would otherwise alter 26 of the 164 stored transcripts — same words and
        same speakers, different line breaks. Harmless, but unrequested.)

        IN_ROOM — delegates to `speaker_attribution`, which separates the
        account into voice clusters and names them from the roll-call.

        The import is function-local because `speaker_attribution` imports THIS
        class for `clean_text` and `build_speaker_labels`; a module-level import
        here would close the cycle.
        """
        if CaptureMode.coerce(capture_mode) is CaptureMode.IN_ROOM:
            from app.processors.speaker_attribution import (
                derive_turns, render, resolve_labels,
            )
            turns = derive_turns(
                transcript_json, capture_mode=CaptureMode.IN_ROOM.value,
            )
            resolutions, diagnostics = resolve_labels(
                turns,
                calendar_attendees=calendar_attendees,
                capture_mode=CaptureMode.IN_ROOM.value,
            )
            logger.info(
                "Formatted in-room transcript: %d turns, %d speaker(s) "
                "(%d named by roll-call, %d unresolved)%s",
                len(turns), len(resolutions),
                diagnostics.resolved_rollcall, diagnostics.unresolved,
                " ⚠ UNDER-CLUSTERING SUSPECTED"
                if diagnostics.under_clustering_suspected else "",
            )
            if diagnostics.under_clustering_suspected:
                # Loud on purpose. Two people introducing themselves into one
                # voice cluster means the diarizer merged them, and the whole
                # meeting's attribution is unreliable. This log line is the
                # only signal until the review flag reaches the UI.
                logger.warning(
                    "Speaker separation looks wrong: %s. Mic placement is the "
                    "usual cause. Attribution needs manual review.",
                    diagnostics.multi_name_clusters,
                )
            return render(turns, resolutions), resolutions, diagnostics

        return TranscriptProcessor._format_online(transcript_json), {}, None

    @staticmethod
    def _format_online(transcript_json: list) -> str:
        """The original `format` body, unchanged. Do not "improve" it — it is
        the reference behaviour the corpus replay asserts against."""
        logger.info(f"Formatting transcript with {len(transcript_json)} blocks.")

        blocks = transcript_json or []
        speaker_labels = TranscriptProcessor.build_speaker_labels(
            ((b.get("participant") or {}).get("id"),
             (b.get("participant") or {}).get("name"))
            for b in blocks
        )

        lines = []
        for block in blocks:
            participant = block.get("participant") or {}
            p_id = participant.get("id")
            # `or` on the lookup, not just `.get(...)`: a label must never
            # come back None and render as the string "None".
            speaker = speaker_labels.get(p_id) or _FALLBACK_SPEAKER

            words = block.get("words", [])
            sentence = TranscriptProcessor.clean_text(
                " ".join([w.get("text", "") for w in words])
            )

            if sentence:
                lines.append(f"{speaker}: {sentence}")

        logger.info(
            "Formatted %d lines of transcript across %d speaker(s).",
            len(lines), len(speaker_labels),
        )
        return "\n".join(lines)
