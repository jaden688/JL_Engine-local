"""
mpf_lint.py - MPF manifest validator / linter.

Usage:
  python tools/mpf_lint.py <manifest.mpf.json> [--assets-root <dir>] [--rewrite-hash] [--strict]

Checks:
  - required meta keys (persona_id, display_name, version, author, license, integrity_sha256)
  - allowed meta keys only (warn if extras unless --strict)
  - integrity hash matches the serialized persona payload (sorted JSON)
  - asset references exist on disk (URLs are skipped)
  - top-level allowed keys only: meta, persona, assets, llm_profiles

Exit codes:
  0 = clean
  1 = warnings/errors found
  2 = manifest could not be read/parsed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


ALLOWED_TOP_LEVEL = {"meta", "persona", "assets", "llm_profiles"}
REQUIRED_META = {"persona_id", "display_name", "version", "author", "license", "integrity_sha256"}
ALLOWED_META = REQUIRED_META | {"signature", "read_only", "created_at"}


def compute_integrity(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def is_url(path_str: str) -> bool:
    return str(path_str).lower().startswith(("http://", "https://"))


def load_manifest(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def lint_manifest(path: Path, assets_root: Path | None, rewrite_hash: bool, strict: bool) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    try:
        manifest = load_manifest(path)
    except Exception as exc:
        return [f"Failed to read '{path}': {exc}"], warnings

    if not isinstance(manifest, dict):
        return [f"Manifest must be an object at top-level: {path}"], warnings

    unknown_top = set(manifest.keys()) - ALLOWED_TOP_LEVEL
    if unknown_top:
        msg = f"Unknown top-level keys: {sorted(unknown_top)}"
        (errors if strict else warnings).append(msg)

    meta = manifest.get("meta", {})
    persona = manifest.get("persona", {})
    assets = manifest.get("assets", {})

    # Meta checks
    if not isinstance(meta, dict):
        errors.append("meta must be an object.")
    else:
        missing = REQUIRED_META - set(meta.keys())
        if missing:
            errors.append(f"Missing required meta keys: {sorted(missing)}")
        unknown_meta = set(meta.keys()) - ALLOWED_META
        if unknown_meta:
            msg = f"Unknown meta keys: {sorted(unknown_meta)}"
            (errors if strict else warnings).append(msg)

        # Integrity
        if isinstance(persona, dict) and meta.get("integrity_sha256"):
            expected = meta.get("integrity_sha256")
            actual = compute_integrity(persona)
            if expected != actual:
                if rewrite_hash:
                    meta["integrity_sha256"] = actual
                    warnings.append("Rewrote integrity_sha256 to match persona payload.")
                else:
                    errors.append("integrity_sha256 does not match persona payload. Use --rewrite-hash to fix.")

    # Asset checks
    if assets and not isinstance(assets, dict):
        errors.append("assets must be an object mapping names to paths/URLs.")
    elif isinstance(assets, dict):
        for name, ref in assets.items():
            if not isinstance(ref, str):
                errors.append(f"Asset '{name}' must be a string path/URL.")
                continue
            if is_url(ref):
                continue  # URL reachability is not checked here
            asset_path = (assets_root or path.parent) / ref
            if not asset_path.exists():
                errors.append(f"Asset '{name}' not found at '{asset_path}'.")

    # Save hash rewrite if requested
    if rewrite_hash and not errors:
        try:
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            errors.append(f"Failed to write updated manifest: {exc}")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Lint an MPF manifest.")
    parser.add_argument("manifest", help="Path to .mpf.json file")
    parser.add_argument("--assets-root", help="Root directory for resolving asset paths", default=None)
    parser.add_argument("--rewrite-hash", action="store_true", help="Rewrite integrity_sha256 to match persona payload")
    parser.add_argument("--strict", action="store_true", help="Treat unknown keys as errors")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    assets_root = Path(args.assets_root) if args.assets_root else None

    errors, warnings = lint_manifest(manifest_path, assets_root, args.rewrite_hash, args.strict)

    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")

    if errors:
        sys.exit(1 if warnings else 1)
    sys.exit(0 if not warnings else 1)


if __name__ == "__main__":
    main()
