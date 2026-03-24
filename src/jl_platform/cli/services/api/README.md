# JL Platform API Module

This package is the full local JL Platform API surface.

Current split:
- `main.py` holds route wiring, runtime helpers, and lifecycle hooks
- `schemas.py` holds request models and API-facing payload defaults

Why the split exists:
- `main.py` is one of the largest files in the repo
- keeping request models in a dedicated module makes route logic easier to scan
- schema-only changes can now be reviewed without paging through the entire API runtime

Safe refactor rule:
- keep route behavior stable first
- move mechanical structures out of `main.py` before changing endpoint semantics
- add tests for defaults any time request models are touched
