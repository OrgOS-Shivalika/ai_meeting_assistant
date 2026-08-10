import re
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
    def incremental_speaker_label(p_id, name, seen: dict, dia_speaker=None) -> str:
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

        # Identity precedence, mirroring the roster-beats-acoustic rule:
        #
        #   name present  -> the platform roster knows this person; the
        #                    participant id is the identity and any
        #                    diarization index is ignored. Roster data is
        #                    exact; diarization is a guess.
        #   no name + dia -> in-room capture: N people share ONE account,
        #                    so the participant id is the same for all of
        #                    them and the diarization index is the only
        #                    thing telling them apart. Identity must be
        #                    the PAIR.
        #   neither       -> fall back to the participant id alone.
        if real:
            key = ("p", p_id)
        elif dia_speaker is not None:
            key = ("d", p_id, dia_speaker)
        elif p_id is not None:
            key = ("p", p_id)
        else:
            return _FALLBACK_SPEAKER

        if key in seen:
            return seen[key]

        if real:
            # How many OTHER ids already claim this same base name?
            taken = sum(
                1 for other in seen.values()
                if other == real or other.startswith(f"{real} (")
            )
            label = real if taken == 0 else f"{real} ({taken + 1})"
        elif dia_speaker is not None:
            # Anonymous by nature — diarization separates voices, it does
            # not identify them. Naming these is the job of the mapping
            # ladder (roll-call / enrollment / manual reassignment).
            label = f"Speaker {dia_speaker}"
        else:
            label = f"{UNNAMED_SPEAKER_PREFIX} {p_id}"

        seen[key] = label
        return label

    @staticmethod
    def format(transcript_json: list) -> str:
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
