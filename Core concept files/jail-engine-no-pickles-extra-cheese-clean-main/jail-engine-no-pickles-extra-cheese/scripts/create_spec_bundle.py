"""Create a self-contained zip bundle of the public JL MPF spec assets.

This script collects the spec README, license, schema, examples, and Python
reference package into a single zip archive so the spec can be extracted or
shared without pulling the rest of the repository.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "jl_mpf_spec_bundle.zip"
BUNDLE_TARGETS: List[str] = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "schema",
    "examples",
    "python/jl_mpf_spec",
]


def _iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            yield from (p for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            yield path
        else:
            raise FileNotFoundError(f"Bundle target not found: {path}")


def create_bundle(output: Path = DEFAULT_OUTPUT) -> Path:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    targets = [ROOT / rel for rel in BUNDLE_TARGETS]
    files = list(_iter_files(targets))

    with ZipFile(output, "w", compression=ZIP_DEFLATED) as zipf:
        for file_path in files:
            arcname = file_path.relative_to(ROOT)
            zipf.write(file_path, arcname)

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle the JL MPF spec into a zip archive.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Path to write the bundle (default: {DEFAULT_OUTPUT.name})",
    )
    args = parser.parse_args()

    bundle_path = create_bundle(args.output)
    print(f"Created bundle at {bundle_path}")


if __name__ == "__main__":
    main()
