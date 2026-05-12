"""Entity name canonicalization for the graph layer.

Single source of truth for the rule that turns a display `name` into a
`canonical_name` used as the dedup key on the `entities` table.

Phase 3 keeps this conservative — trim, lowercase, collapse whitespace,
strip surrounding punctuation. Anything beyond that (alias resolution,
embedding-based fuzzy matching, NER cleanup) lands when we know which
mistakes actually hurt retrieval, not before.

The function is pure — no DB, no IO. That keeps both the extractor and
the persistence layer (3C) calling the same rule, and tests can pin
behavior precisely.
"""
from __future__ import annotations

import re
import unicodedata


# Punctuation we strip from the outer edges of a name. Internal
# punctuation is left alone — "Acme, Inc." canonicalizes to "acme, inc"
# rather than "acme inc" because the comma is structural information.
_OUTER_PUNCT = ".,;:!?\"'`()[]{}<>"
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_entity_name(name: str) -> str:
    """Return the canonical form of an entity display name.

    Rules (in order):
      1. Unicode-normalize to NFKC so "ﬁ" -> "fi", "Ｓarah" -> "Sarah", etc.
      2. Strip leading/trailing whitespace.
      3. Lowercase.
      4. Collapse internal whitespace to single ASCII spaces.
      5. Strip outer punctuation (one pass from each side).

    An empty or whitespace-only input returns an empty string — caller
    decides whether to treat that as an extraction error.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = s.strip()
    if not s:
        return ""
    s = s.lower()
    s = _WHITESPACE_RE.sub(" ", s)
    # Strip outer punctuation iteratively in case the LLM wrapped a name
    # like '"Phoenix"' or '(Project) Phoenix' — peel from both ends.
    while s and s[0] in _OUTER_PUNCT:
        s = s[1:].lstrip()
    while s and s[-1] in _OUTER_PUNCT:
        s = s[:-1].rstrip()
    return s
