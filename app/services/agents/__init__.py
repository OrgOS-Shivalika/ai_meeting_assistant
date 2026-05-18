"""Phase 7 — Agent Control Dashboard service layer.

Modules:

  publish.py       — draft → published / rollback / version-number generation
  diff.py          — version-vs-version diff (per modular section + key-level
                     diffs of retrieval/model/tool configs)

Future slices add:
  resolver.py      — hierarchical config resolver (7C)
  composition.py   — modular prompt → assembled chat message (7C/7D)
  cache.py         — LRU + epoch invalidation (7C)
  playground.py    — sandboxed retrieval+synth runner (7E)
  seed_defaults.py — filesystem → DB migration (7D)
  analytics.py     — daily rollup queries (7F)
  eval_gate.py     — Phase 5F harness integration (7H)
"""
