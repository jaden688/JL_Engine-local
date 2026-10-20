#!/usr/bin/env python3
"""
Export a SQLite code corpus to Microsoft Foundry fine-tuning JSONL.

The source database is expected to expose:
  - `repos`: repository metadata, including `allowed` and `description`
  - `files`: file contents, paths, languages, and blob SHAs

The exporter supports two templates:
  - analysis: summarize the file and identify symbols
  - completion: continue the file from a prefix

Both templates emit Foundry-compatible `messages` JSONL.

Foundry fine-tuning expects JSONL in conversational format. This script writes
UTF-8 with BOM so it can be uploaded directly.

Usage:
  python scripts/export_foundry_finetune.py ^
    --db C:\\Users\\J_lin\\Desktop\\jlenginedata\\github_dataset.db ^
    --out-dir C:\\Users\\J_lin\\Desktop\\jlenginedata\\foundry_export
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


DEFAULT_DB = Path(r"C:\Users\J_lin\Desktop\jlenginedata\github_dataset.db")
DEFAULT_VALIDATION_RATIO = 0.1
DEFAULT_EXCERPT_CHARS = 12000
DEFAULT_MIN_CHARS = 80
DEFAULT_TEMPLATE = "analysis"
DEFAULT_COMPLETION_PREFIX_CHARS = 1200
DEFAULT_COMPLETION_ANSWER_CHARS = 4000
DEFAULT_COMPLETION_MIN_ANSWER_CHARS = 120
DEFAULT_SYSTEM_PROMPT = (
    "You are a careful code analyst. "
    "Summarize repository files succinctly, accurately, and without inventing details."
)
DEFAULT_COMPLETION_SYSTEM_PROMPT = (
    "You are a code completion model. "
    "Continue the file exactly from the provided prefix. "
    "Output only the continuation."
)


@dataclass(frozen=True)
class RepoRow:
    full_name: str
    description: str
    homepage: str
    language: str
    stars: int
    forks: int
    license_spdx: str
    allowed: bool


@dataclass(frozen=True)
class FileRow:
    repo_full_name: str
    path: str
    language: str
    sha: str
    size: int
    symbols_json: str
    content: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Foundry fine-tuning JSONL from a SQLite corpus.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to the SQLite source database.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for train/validation JSONL. Defaults to a sibling folder next to the DB.",
    )
    parser.add_argument(
        "--validation-ratio",
        type=float,
        default=DEFAULT_VALIDATION_RATIO,
        help="Fraction of examples to place in validation.",
    )
    parser.add_argument(
        "--excerpt-chars",
        type=int,
        default=DEFAULT_EXCERPT_CHARS,
        help="Maximum number of characters from each file to include in the user prompt.",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=DEFAULT_MIN_CHARS,
        help="Minimum content length required to keep a file.",
    )
    parser.add_argument(
        "--template",
        choices=("analysis", "completion"),
        default=DEFAULT_TEMPLATE,
        help="Training example template to export.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on the number of files processed after filtering.",
    )
    parser.add_argument(
        "--include-unallowed",
        action="store_true",
        help="Include repos whose `allowed` flag is false.",
    )
    parser.add_argument(
        "--include-unsupported-languages",
        action="store_true",
        help="Include rows even when language metadata is missing.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for the deterministic train/validation split hash.",
    )
    parser.add_argument(
        "--completion-prefix-chars",
        type=int,
        default=DEFAULT_COMPLETION_PREFIX_CHARS,
        help="Prefix length used for code-completion examples.",
    )
    parser.add_argument(
        "--completion-answer-chars",
        type=int,
        default=DEFAULT_COMPLETION_ANSWER_CHARS,
        help="Maximum continuation length used for code-completion examples.",
    )
    parser.add_argument(
        "--completion-min-answer-chars",
        type=int,
        default=DEFAULT_COMPLETION_MIN_ANSWER_CHARS,
        help="Minimum continuation length required to keep a code-completion row.",
    )
    return parser.parse_args()


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sentence_case(text: str) -> str:
    text = clean_spaces(text)
    if not text:
        return text
    return text[0].upper() + text[1:]


def short_text(text: str, limit: int) -> str:
    text = clean_spaces(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def first_sentence(text: str) -> str:
    text = clean_spaces(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    return parts[0]


def parse_symbols(symbols_json: Optional[str]) -> List[str]:
    if not symbols_json:
        return []
    try:
        raw = json.loads(symbols_json)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    symbols: List[str] = []
    for item in raw:
        if item is None:
            continue
        name = str(item).strip()
        if name:
            symbols.append(name)
    return symbols


def file_stem(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    base = normalized.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    return stem or base or "file"


def compact_path(path: str) -> str:
    return path.replace("\\", "/")


def looks_like_boilerplate(text: str) -> bool:
    lowered = text.lower()
    markers = ["copyright", "all rights reserved", "permission is hereby", "license", "do not distribute"]
    hit_count = sum(1 for marker in markers if marker in lowered)
    return hit_count >= 2


def extract_opening_text(content: str) -> str:
    content = normalize_text(content)
    if not content:
        return ""

    # Prefer an early docstring if one exists.
    doc_match = re.search(r'(?s)\A(?:\ufeff)?(?:\s*#.*\n|\s*)*(?P<quote>"""|\'\'\')(?P<body>.*?)(?P=quote)', content)
    if doc_match:
        body = clean_spaces(doc_match.group("body"))
        if body and not looks_like_boilerplate(body):
            return first_sentence(body)

    # Fall back to a leading comment block.
    lines = content.splitlines()
    comment_lines: List[str] = []
    for line in lines[:40]:
        stripped = line.strip()
        if not stripped:
            if comment_lines:
                break
            continue
        if stripped.startswith("#") or stripped.startswith("//"):
            comment_lines.append(stripped.lstrip("#/ ").strip())
            continue
        if stripped.startswith("/*") or stripped.startswith("*"):
            cleaned = stripped.lstrip("/* ").rstrip("*/ ").strip()
            if cleaned:
                comment_lines.append(cleaned)
            continue
        break

    if comment_lines:
        body = clean_spaces(" ".join(comment_lines))
        if body and not looks_like_boilerplate(body):
            return first_sentence(body)

    return ""


def infer_role(path: str, language: str, symbols: List[str]) -> str:
    lower_path = compact_path(path).lower()
    lower_lang = (language or "").lower()
    lower_symbols = [s.lower() for s in symbols]

    if "/test" in lower_path or lower_path.startswith("test/") or lower_path.endswith("_test.py") or lower_path.startswith("tests/"):
        return "test"
    if lower_path.endswith((".html", ".htm", ".tsx", ".jsx", ".css")) or lower_lang in {"html", "typescript", "javascript"}:
        return "front-end"
    if "adapter" in lower_path or any("adapter" in s for s in lower_symbols):
        return "adapter"
    if "schema" in lower_path or "types" in lower_path or "config" in lower_path or "settings" in lower_path:
        return "schema/config"
    if lower_path.endswith(("main.py", "app.py", "main.jl", "app.jl", "index.js", "index.ts", "index.html")):
        return "entrypoint"
    if "cli" in lower_path or "command" in lower_path:
        return "cli"
    if lower_path.endswith((".md", ".rst")) or lower_lang == "markdown":
        return "documentation"
    if any(s.startswith("test_") for s in lower_symbols):
        return "test"
    if any(s in {"main", "run", "process", "build", "execute"} for s in lower_symbols):
        return "entrypoint"
    return "module"


def summarize_symbols(symbols: List[str], limit: int = 8) -> str:
    if not symbols:
        return "none"
    trimmed = symbols[:limit]
    text = ", ".join(trimmed)
    if len(symbols) > limit:
        text += f", +{len(symbols) - limit} more"
    return text


def build_summary(row: FileRow, repo: RepoRow, opening_text: str, symbols: List[str], role: str) -> str:
    stem = file_stem(row.path)
    repo_name = repo.full_name.rsplit("/", 1)[-1]

    if opening_text:
        return sentence_case(opening_text)

    symbol_text = summarize_symbols(symbols, limit=4)

    if role == "test":
        return f"Test file for {stem} that exercises the surrounding module."
    if role == "front-end":
        return f"Front-end file for {stem} that defines UI behavior or presentation for {repo_name}."
    if role == "adapter":
        return f"Adapter module for {repo_name} that bridges internal data structures to another representation."
    if role == "schema/config":
        return f"Schema or configuration file for {repo_name}."
    if role == "entrypoint":
        return f"Entry point that wires together {symbol_text if symbol_text != 'none' else stem}."
    if role == "documentation":
        return f"Documentation file for {repo_name}."
    if symbols:
        return f"Module that defines {symbol_text}."
    return f"{row.language or 'Text'} file for {stem} with supporting implementation details."


def build_notes(row: FileRow, role: str, symbols: List[str], truncated: bool, opening_text: str) -> str:
    notes: List[str] = []
    if role in {"entrypoint", "cli", "front-end", "test", "adapter", "schema/config"}:
        notes.append(f"Likely {role} code.")
    if symbols:
        notes.append(f"Top-level symbols detected: {summarize_symbols(symbols, limit=6)}.")
    else:
        notes.append("No top-level symbols were detected in the ingested metadata.")
    if truncated:
        notes.append("The user prompt includes a truncated excerpt of the file.")
    if opening_text and looks_like_boilerplate(opening_text):
        notes.append("The opening text looks like header or license boilerplate.")
    return " ".join(notes)


def deterministic_split_key(seed: int, repo_full_name: str, path: str, sha: str) -> int:
    payload = f"{seed}\0{repo_full_name}\0{path}\0{sha}".encode("utf-8", "ignore")
    digest = hashlib.sha256(payload).hexdigest()
    return int(digest[:8], 16)


def is_validation(seed: int, ratio: float, repo_full_name: str, path: str, sha: str) -> bool:
    bucket = deterministic_split_key(seed, repo_full_name, path, sha) % 10000
    return bucket < int(ratio * 10000)


def load_repos(con: sqlite3.Connection) -> Dict[str, RepoRow]:
    rows = con.execute(
        """
        SELECT full_name, description, homepage, language, stars, forks, license_spdx, allowed
        FROM repos
        """
    ).fetchall()
    repos: Dict[str, RepoRow] = {}
    for row in rows:
        repo = RepoRow(
            full_name=str(row["full_name"] or ""),
            description=str(row["description"] or ""),
            homepage=str(row["homepage"] or ""),
            language=str(row["language"] or ""),
            stars=int(row["stars"] or 0),
            forks=int(row["forks"] or 0),
            license_spdx=str(row["license_spdx"] or ""),
            allowed=bool(row["allowed"]),
        )
        repos[repo.full_name] = repo
        repos[repo.full_name.lower()] = repo
    return repos


def load_files(con: sqlite3.Connection, repo_names: Optional[set[str]] = None) -> Iterator[FileRow]:
    params: Tuple[Any, ...] = ()
    query = """
        SELECT repo_full_name, path, language, sha, size, symbols_json, content
        FROM files
    """
    if repo_names:
        placeholders = ",".join("?" for _ in repo_names)
        query += f" WHERE lower(repo_full_name) IN ({placeholders})"
        params = tuple(sorted(repo_names))
    query += " ORDER BY repo_full_name, path"
    rows = con.execute(query, params)
    for row in rows:
        yield FileRow(
            repo_full_name=str(row["repo_full_name"] or ""),
            path=str(row["path"] or ""),
            language=str(row["language"] or ""),
            sha=str(row["sha"] or ""),
            size=int(row["size"] or 0),
            symbols_json=str(row["symbols_json"] or ""),
            content=str(row["content"] or ""),
        )


def build_user_prompt(row: FileRow, repo: RepoRow, symbols: List[str], excerpt: str) -> str:
    repo_description = short_text(repo.description, 240) or "No description available."
    symbol_text = summarize_symbols(symbols, limit=12)
    return (
        "Analyze this repository file for a coding teammate and return:\n"
        "Summary: one sentence\n"
        "Key symbols: a short comma-separated list\n"
        "Notes: one short sentence\n\n"
        f"Repository: {repo.full_name}\n"
        f"Repo description: {repo_description}\n"
        f"Path: {compact_path(row.path)}\n"
        f"Language: {row.language or 'unknown'}\n"
        f"Known symbols: {symbol_text}\n\n"
        "File excerpt:\n"
        "<<<BEGIN FILE>>>\n"
        f"{excerpt}\n"
        "<<<END FILE>>>"
    )


def build_completion_prompt(row: FileRow, repo: RepoRow, symbols: List[str], prefix: str) -> str:
    symbol_text = summarize_symbols(symbols, limit=12)
    return (
        "Complete the file from the prefix below. Preserve syntax, indentation, and style.\n"
        f"Repository: {repo.full_name}\n"
        f"Path: {compact_path(row.path)}\n"
        f"Language: {row.language or 'unknown'}\n"
        f"Known symbols: {symbol_text}\n\n"
        "Prefix:\n"
        "<<<BEGIN PREFIX>>>\n"
        f"{prefix}\n"
        "<<<END PREFIX>>>"
    )


def make_analysis_example(row: FileRow, repo: RepoRow, excerpt_chars: int) -> Tuple[Dict[str, Any], bool]:
    content = normalize_text(row.content)
    symbols = parse_symbols(row.symbols_json)
    opening_text = extract_opening_text(content)
    truncated = len(content) > excerpt_chars
    excerpt = content[:excerpt_chars].rstrip()
    role = infer_role(row.path, row.language, symbols)
    summary = build_summary(row, repo, opening_text, symbols, role)
    notes = build_notes(row, role, symbols, truncated, opening_text)
    assistant_content = "\n".join(
        [
            f"Summary: {summary}",
            f"Key symbols: {summarize_symbols(symbols, limit=8)}",
            f"Notes: {notes}",
        ]
    )
    example = {
        "messages": [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(row, repo, symbols, excerpt)},
            {"role": "assistant", "content": assistant_content},
        ]
    }
    return example, truncated


def make_completion_example(
    row: FileRow,
    repo: RepoRow,
    prefix_chars: int,
    answer_chars: int,
    min_answer_chars: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    content = normalize_text(row.content)
    symbols = parse_symbols(row.symbols_json)
    if len(content) <= prefix_chars + min_answer_chars:
        return None, False

    prefix = content[:prefix_chars].rstrip()
    suffix = content[prefix_chars : prefix_chars + answer_chars]
    if not suffix.strip():
        return None, False

    truncated = len(content) > prefix_chars + answer_chars
    example = {
        "messages": [
            {"role": "system", "content": DEFAULT_COMPLETION_SYSTEM_PROMPT},
            {"role": "user", "content": build_completion_prompt(row, repo, symbols, prefix)},
            {"role": "assistant", "content": suffix.rstrip()},
        ]
    }
    return example, truncated


def ensure_out_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
            count += 1
    return count


def main() -> int:
    args = parse_args()
    con = connect(args.db)
    repos = load_repos(con)
    repo_filter: Optional[set[str]] = None
    if not args.include_unallowed:
        repo_filter = {repo.full_name.lower() for repo in repos.values() if repo.allowed}

    if args.out_dir is None:
        default_name = "foundry_export_completion" if args.template == "completion" else "foundry_export"
        out_dir = ensure_out_dir(args.db.parent / default_name)
    else:
        out_dir = ensure_out_dir(args.out_dir)
    train_path = out_dir / "train.jsonl"
    validation_path = out_dir / "validation.jsonl"
    manifest_path = out_dir / "manifest.json"

    seen_sha: set[str] = set()
    seen_content_hash: set[str] = set()
    skipped_missing_repo = 0
    skipped_unallowed = 0
    skipped_language = 0
    skipped_short = 0
    skipped_duplicate = 0
    processed = 0
    kept = 0
    validation_examples: List[Dict[str, Any]] = []
    train_examples: List[Dict[str, Any]] = []
    role_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    repo_counts: Counter[str] = Counter()
    truncated_count = 0

    for row in load_files(con, repo_filter):
        repo = repos.get(row.repo_full_name) or repos.get(row.repo_full_name.lower())
        if repo is None:
            skipped_missing_repo += 1
            continue
        if not args.include_unallowed and not repo.allowed:
            skipped_unallowed += 1
            continue
        if not args.include_unsupported_languages and not row.language:
            skipped_language += 1
            continue
        content = normalize_text(row.content)
        if len(content.strip()) < args.min_chars:
            skipped_short += 1
            continue

        dedupe_key = row.sha or hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
        if dedupe_key in seen_sha:
            skipped_duplicate += 1
            continue
        content_hash = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
        if content_hash in seen_content_hash:
            skipped_duplicate += 1
            continue
        seen_sha.add(dedupe_key)
        seen_content_hash.add(content_hash)

        if args.template == "completion":
            example, truncated = make_completion_example(
                row,
                repo,
                args.completion_prefix_chars,
                args.completion_answer_chars,
                args.completion_min_answer_chars,
            )
        else:
            example, truncated = make_analysis_example(row, repo, args.excerpt_chars)
        if example is None:
            skipped_short += 1
            continue

        processed += 1
        kept += 1
        if truncated:
            truncated_count += 1

        role = infer_role(row.path, row.language, parse_symbols(row.symbols_json))
        role_counts[role] += 1
        language_counts[row.language or "unknown"] += 1
        repo_counts[repo.full_name] += 1

        if is_validation(args.seed, args.validation_ratio, row.repo_full_name, row.path, row.sha or dedupe_key):
            validation_examples.append(example)
        else:
            train_examples.append(example)

        if args.max_files is not None and kept >= args.max_files:
            break

    train_written = write_jsonl(train_path, train_examples)
    validation_written = write_jsonl(validation_path, validation_examples)

    manifest = {
        "source_db": str(args.db),
        "out_dir": str(out_dir),
        "train_file": str(train_path),
        "validation_file": str(validation_path),
        "template": args.template,
        "validation_ratio": args.validation_ratio,
        "excerpt_chars": args.excerpt_chars,
        "min_chars": args.min_chars,
        "completion_prefix_chars": args.completion_prefix_chars,
        "completion_answer_chars": args.completion_answer_chars,
        "completion_min_answer_chars": args.completion_min_answer_chars,
        "max_files": args.max_files,
        "include_unallowed": args.include_unallowed,
        "include_unsupported_languages": args.include_unsupported_languages,
        "seed": args.seed,
        "rows_written": {
            "train": train_written,
            "validation": validation_written,
        },
        "rows_processed": processed,
        "rows_kept": kept,
        "rows_skipped": {
            "missing_repo": skipped_missing_repo,
            "unallowed_repo": skipped_unallowed,
            "missing_language": skipped_language,
            "too_short": skipped_short,
            "duplicate": skipped_duplicate,
        },
        "truncated_examples": truncated_count,
        "top_roles": role_counts.most_common(10),
        "top_languages": language_counts.most_common(10),
        "top_repos": repo_counts.most_common(10),
    }
    with manifest_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Foundry export complete: {out_dir}")
    print(f"  template:    {args.template}")
    print(f"  train:       {train_written}")
    print(f"  validation:  {validation_written}")
    print(f"  kept:        {kept}")
    print(f"  truncated:   {truncated_count}")
    print(f"  skipped dup: {skipped_duplicate}")
    print(f"  skipped repo:{skipped_unallowed + skipped_missing_repo}")
    print(f"  manifest:    {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
