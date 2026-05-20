"""Phase 8 — prebuilt enterprise template system.

Public modules:

  catalog.py    — code-defined platform catalog (teams + categories +
                  agents + bundles). Single source of truth; seed
                  reads from here.
  registry.py   — read-only TemplateRegistryService over the
                  `template_*` tables.
  seed_catalog.py — idempotent DB populator. Run via
                  `app/scripts/seed_global_templates.py`.

8B+ add: provisioning.py, divergence.py, upgrade.py, resolver.py.
"""
