"""
mpf_compiler.py - Compile persona JSON schemas into binary MPF blobs.

Usage examples:
  python mpf_compiler.py personas/SparkByte_Full.json
  python mpf_compiler.py personas --recursive --out-dir personas/bin
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from framework.mpf.binary_io import dump_mpf


def _iter_inputs(paths: Iterable[str], recursive: bool) -> list[Path]:
    resolved: list[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            if recursive:
                resolved.extend(path.rglob("*.json"))
            else:
                resolved.extend(path.glob("*.json"))
        else:
            resolved.append(path)
    return resolved


def _compile_file(src: Path, dest: Path, compress: bool) -> None:
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    dump_mpf(data, dest, compress=compress)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile persona JSON to binary MPF.")
    parser.add_argument("inputs", nargs="+", help="Persona JSON files or directories to compile.")
    parser.add_argument("--out-dir", type=Path, help="Directory to place compiled MPF files.")
    parser.add_argument("--recursive", action="store_true", help="Recursively scan directories for JSON.")
    parser.add_argument("--no-compress", action="store_true", help="Disable zlib compression.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing MPF files.")
    args = parser.parse_args()

    targets = _iter_inputs(args.inputs, args.recursive)
    if not targets:
        print("[MPF Compiler] No input files found.")
        return 1

    out_dir = args.out_dir
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    compiled = 0
    for src in targets:
        if src.suffix.lower() != ".json":
            print(f"[MPF Compiler] Skipping non-JSON file: {src}")
            continue
        if not src.exists():
            print(f"[MPF Compiler] Missing file: {src}")
            continue

        dest = (out_dir / f"{src.stem}.mpf") if out_dir else src.with_suffix(".mpf")
        if dest.exists() and not args.force:
            print(f"[MPF Compiler] Exists (use --force to overwrite): {dest}")
            continue

        try:
            _compile_file(src, dest, compress=not args.no_compress)
            compiled += 1
            print(f"[MPF Compiler] Wrote {dest}")
        except Exception as exc:
            print(f"[MPF Compiler] Failed to compile '{src}': {exc}")

    print(f"[MPF Compiler] Done. Compiled {compiled} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
