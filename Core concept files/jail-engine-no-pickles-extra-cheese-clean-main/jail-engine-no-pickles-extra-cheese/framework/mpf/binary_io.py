"""
Safe + efficient MPF v2 container for Codex / on-device use.

Design goals:
- No pickle. JSON-only payloads to avoid code execution issues.
- Simple, fixed header format for fast parsing.
- Minimal allocations and abstractions.
- Optional compression and checksum for devices that can afford them.

File layout (all bytes):
    MAGIC[4] = b"MPFB"
    VERSION[1] = 0x02
    FLAGS[1]   = bitmask:
        FLAG_COMPRESSED = 0x01
        FLAG_CHECKSUM   = 0x02
    [CHECKSUM[32]] if FLAG_CHECKSUM set = SHA-256 of *payload bytes as stored*
    PAYLOAD[...] = JSON UTF-8 bytes, optionally zlib-compressed

If the file does NOT start with MAGIC, it is treated as plain JSON UTF-8.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path
from typing import Any, Mapping

# --- Format constants --------------------------------------------------------

MAGIC = b"MPFB"
VERSION = 2

FLAG_COMPRESSED = 0x01
FLAG_CHECKSUM = 0x02

CHECKSUM_LEN = 32  # SHA-256


class MPFDecodeError(ValueError):
    """Raised when an MPF payload cannot be decoded."""


# --- Internal helpers --------------------------------------------------------


def _ensure_mapping(data: Any) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(
            "Persona payload must be a mapping (dict-like). "
            f"Got {type(data).__name__!r}."
        )
    return data


def _encode_json(
    data: Mapping[str, Any],
    *,
    deterministic: bool = False,
) -> bytes:
    """
    Encode mapping as JSON UTF-8 bytes.

    deterministic=False:
        - Faster on-device, may change key order between runs.
    deterministic=True:
        - Uses sort_keys and compact separators for stable output
          (useful if you rely on binary equality or caching keyed by blob).
    """
    if deterministic:
        return json.dumps(
            data,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")

    return json.dumps(
        data,
        ensure_ascii=False,
    ).encode("utf-8")


def _decode_json(payload: bytes) -> Mapping[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise MPFDecodeError(f"Failed to decode MPF JSON payload: {exc}") from exc

    if not isinstance(data, Mapping):
        raise MPFDecodeError(
            f"MPF payload did not decode to a mapping (got {type(data).__name__!r})."
        )
    return data


def _encode_mpf_bytes(
    data: Mapping[str, Any],
    *,
    compress: bool = True,
    checksum: bool = True,
    deterministic_json: bool = False,
) -> bytes:
    """
    Encode mapping into MPF v2 bytes.

    compress:
        True  -> zlib.compress payload bytes.
        False -> store raw JSON.
    checksum:
        True  -> include SHA-256 of stored payload bytes in header.
        False -> no checksum.
    deterministic_json:
        True  -> sorted keys for stable binary blob.
        False -> faster JSON encoding.
    """
    _ensure_mapping(data)

    # Encode JSON first.
    payload = _encode_json(data, deterministic=deterministic_json)

    flags = 0

    # Optional compression.
    if compress:
        payload = zlib.compress(payload)
        flags |= FLAG_COMPRESSED

    header = bytearray()
    header += MAGIC
    header.append(VERSION)
    header.append(flags)

    # Optional checksum of payload bytes as stored.
    if checksum:
        flags |= FLAG_CHECKSUM
        header[-1] = flags  # update flags after setting bit
        digest = hashlib.sha256(payload).digest()
        # Fixed-size checksum.
        header += digest

    return bytes(header) + payload


def _decode_mpf_bytes(raw: bytes) -> Mapping[str, Any]:
    """
    Decode MPF v2 bytes into mapping.
    """
    # Basic header length: MAGIC(4) + VERSION(1) + FLAGS(1) = 6 bytes
    if len(raw) < 6:
        raise MPFDecodeError("MPF payload too short for header.")

    if not raw.startswith(MAGIC):
        raise MPFDecodeError("Missing MPF magic header.")

    version = raw[4]
    flags = raw[5]

    if version != VERSION:
        raise MPFDecodeError(
            f"Unsupported MPF version {version} (expected {VERSION})."
        )

    offset = 6

    # Optional checksum.
    checksum_expected = None
    if flags & FLAG_CHECKSUM:
        if len(raw) < offset + CHECKSUM_LEN:
            raise MPFDecodeError("MPF payload missing checksum bytes.")
        checksum_expected = raw[offset : offset + CHECKSUM_LEN]
        offset += CHECKSUM_LEN

    payload = raw[offset:]

    if not payload:
        raise MPFDecodeError("MPF payload is empty.")

    # Verify checksum if present.
    if checksum_expected is not None:
        actual = hashlib.sha256(payload).digest()
        if actual != checksum_expected:
            raise MPFDecodeError("MPF payload checksum mismatch.")

    # Decompress if needed.
    if flags & FLAG_COMPRESSED:
        try:
            payload = zlib.decompress(payload)
        except zlib.error as exc:
            raise MPFDecodeError(f"Failed to decompress MPF payload: {exc}") from exc

    # Decode JSON into mapping.
    return _decode_json(payload)


# --- Public API: in-memory ---------------------------------------------------


def dumps_mpf(
    data: Mapping[str, Any],
    *,
    compress: bool = True,
    checksum: bool = True,
    deterministic_json: bool = False,
) -> bytes:
    """
    Serialize a mapping into MPF v2 bytes.

    Recommended on-device settings:

        # Fastest: no compression, checksum still on
        dumps_mpf(data, compress=False, checksum=True, deterministic_json=False)

        # Smallest: compression + checksum + deterministic (for caching)
        dumps_mpf(data, compress=True, checksum=True, deterministic_json=True)
    """
    return _encode_mpf_bytes(
        data,
        compress=compress,
        checksum=checksum,
        deterministic_json=deterministic_json,
    )


def loads_mpf(raw: bytes) -> Mapping[str, Any]:
    """
    Load persona payload from either:
      - MPF v2 bytes, or
      - plain JSON UTF-8 bytes.

    Returns a mapping (dict-like).
    """
    if raw.startswith(MAGIC):
        return _decode_mpf_bytes(raw)

    # Fallback: treat as plain JSON.
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise MPFDecodeError(f"Failed to decode JSON payload: {exc}") from exc

    if not isinstance(data, Mapping):
        raise MPFDecodeError(
            f"JSON payload did not decode to a mapping (got {type(data).__name__!r})."
        )
    return data


# --- Public API: file-based --------------------------------------------------


def dump_mpf(
    data: Mapping[str, Any],
    path: str | Path,
    *,
    compress: bool = True,
    checksum: bool = True,
    deterministic_json: bool = False,
) -> None:
    """
    Serialize a mapping into an MPF v2 file on disk.

    For on-device / mobile-style environments you probably want:
        dump_mpf(data, path, compress=False, checksum=True, deterministic_json=False)
    """
    file_path = Path(path)
    blob = dumps_mpf(
        data,
        compress=compress,
        checksum=checksum,
        deterministic_json=deterministic_json,
    )
    file_path.write_bytes(blob)


def load_mpf(path: str | Path) -> Mapping[str, Any]:
    """
    Load persona payload from file:

      - MPF v2 (MAGIC-prefixed), or
      - plain JSON.

    Returns a mapping (dict-like).
    """
    file_path = Path(path)
    raw = file_path.read_bytes()
    return loads_mpf(raw)
