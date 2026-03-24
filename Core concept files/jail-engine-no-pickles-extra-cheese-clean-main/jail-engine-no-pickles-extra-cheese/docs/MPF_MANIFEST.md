# MPF Manifest + Validator

## Overview
- MPF manifests live as `<persona>.mpf.json` and wrap persona JSON with provenance and assets.
- Use `tools/mpf_lint.py` to validate, enforce allowed keys, and keep integrity hashes in sync.

## Structure
Top-level keys (only these are allowed):
- `meta`: provenance + integrity
- `persona`: the persona payload (existing format)
- `assets`: map of asset names to local paths or URLs
- `llm_profiles`: optional LLM profile overrides

`meta` required fields:
- `persona_id`, `display_name`, `version`, `author`, `license`, `integrity_sha256`
Optional: `signature`, `read_only` (bool), `created_at`.

Integrity: `integrity_sha256` is computed over the JSON-serialized `persona` object (sorted keys, UTF-8). Use `--rewrite-hash` to set it.

Read-only: set `read_only: true` to load the persona in “bundle” mode (UI shows a read-only badge, blocks disk writes and tool calls).

## Validator CLI
```
python tools/mpf_lint.py personas/SparkByte.mpf.json \
  --assets-root personas \
  --rewrite-hash \
  --strict
```
Checks:
- required meta keys present
- only allowed meta keys (warn or error with --strict)
- integrity hash matches persona payload (rewrite when requested)
- assets exist on disk (URLs are ignored)
- only allowed top-level keys

Exit codes: 0 = clean, 1 = warnings/errors, 2 = parse failure (file read error).

## Template
- See `docs/MPF_MANIFEST_TEMPLATE.mpf.json` for a ready-to-fill example.

## UI surfacing
- On load, the app displays provenance (author/version/license/hash status) and marks read-only personas.
- Read-only personas disable tool calls and skip disk persistence; memory stays in-memory for the session.
