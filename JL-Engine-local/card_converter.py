"""
card_converter.py
PNG/JSON character card → JL MPF fat-agent payload converter.

Handles:
  - SillyTavern PNG cards (character data embedded in PNG text chunks)
  - SillyTavern/Character Tavern JSON cards (v1 and v2 spec)
  - Generic persona JSON blobs

Pipeline:
  1. Extract card data from PNG metadata or JSON file
  2. Normalize via modules/card2mpf.py (the engine's own normalizer)
  3. Call the engine LLM to generate missing fat-agent fields
     (archetype, sentence_style, signature_moves, tonal_range, etc.)
  4. Assemble the final .jlmpf.json payload
  5. Optionally write to disk and/or register with the engine

All PNG parsing uses only stdlib (struct, zlib, base64).
"""

from __future__ import annotations

import base64
import json
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ── Path setup so we can import modules/card2mpf.py ─────────────────────────
_HERE = Path(__file__).resolve().parent
_ENGINE_ROOT = _HERE.parent
_MODULES = _ENGINE_ROOT / "modules"
for _p in (_ENGINE_ROOT, _MODULES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from card2mpf import normalize_card, expandAgent, load_card as _new_load_card
    _HAS_NEW_CARD2MPF = True
except ImportError:
    _HAS_NEW_CARD2MPF = False

ENGINE_BASE = "http://127.0.0.1:8000"

# ════════════════════════════════════════════════════════════════════════════
#  PNG EXTRACTION (stdlib only)
# ════════════════════════════════════════════════════════════════════════════

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _iter_png_chunks(data: bytes):
    if not data.startswith(_PNG_SIG):
        return
    offset = len(_PNG_SIG)
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > len(data):
            break
        yield chunk_type, data[chunk_start:chunk_end]
        offset = chunk_end + 4


def _extract_png_texts(data: bytes) -> list[str]:
    texts = []
    for chunk_type, chunk_data in _iter_png_chunks(data):
        if chunk_type == b"tEXt":
            if b"\x00" in chunk_data:
                _, text_bytes = chunk_data.split(b"\x00", 1)
                try:
                    texts.append(text_bytes.decode("utf-8"))
                except UnicodeDecodeError:
                    texts.append(text_bytes.decode("latin-1", errors="ignore"))
        elif chunk_type == b"zTXt":
            if b"\x00" not in chunk_data or len(chunk_data) < 3:
                continue
            _, rest = chunk_data.split(b"\x00", 1)
            if not rest or rest[0:1] != b"\x00":
                continue
            try:
                texts.append(zlib.decompress(rest[1:]).decode("utf-8"))
            except Exception:
                continue
        elif chunk_type == b"iTXt":
            parts = chunk_data.split(b"\x00", 5)
            if len(parts) < 6:
                continue
            _, comp_flag, comp_method, _lang, _trans, text = parts
            if comp_flag == b"\x01" and comp_method == b"\x00":
                try:
                    text = zlib.decompress(text)
                except Exception:
                    continue
            try:
                texts.append(text.decode("utf-8"))
            except UnicodeDecodeError:
                texts.append(text.decode("latin-1", errors="ignore"))
    return texts


def _try_decode_payload(raw: str) -> dict | None:
    for candidate in (raw, raw.strip()):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    try:
        b64 = base64.b64decode(raw.strip(), validate=False)
    except Exception:
        return None
    for attempt in (b64, None):
        if attempt is None:
            try:
                attempt = zlib.decompress(b64)
            except Exception:
                continue
        try:
            return json.loads(attempt.decode("utf-8", errors="replace").lstrip("\ufeff"))
        except Exception:
            continue
    return None


def load_card_from_png(path: Path) -> dict:
    data = path.read_bytes()
    texts = _extract_png_texts(data)
    if not texts:
        raise ValueError(f"No embedded card data found in '{path.name}'.")
    for text in texts:
        card = _try_decode_payload(text)
        if isinstance(card, dict):
            return card
    raise ValueError(f"Could not decode card payload from '{path.name}'.")


def load_card(path: Path) -> dict:
    """Load a card from .png or .json/.mpf file."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".png":
        return load_card_from_png(path)
    if suffix in {".json", ".mpf", ".jlmpf"}:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    raise ValueError(f"Unsupported file type '{suffix}'. Expected .png, .json, or .mpf.")


# ════════════════════════════════════════════════════════════════════════════
#  NORMALIZE
# ════════════════════════════════════════════════════════════════════════════

def _normalize_card(card: dict) -> tuple[dict, list[str]]:
    """Normalize card data using the engine's card2mpf module."""
    if _HAS_NEW_CARD2MPF:
        return normalize_card(card)
    # Minimal fallback if module unavailable
    name = (
        card.get("name") or card.get("char_name") or
        (card.get("data") or {}).get("name") or "Unnamed"
    )
    role = card.get("role") or "Agent"
    desc = card.get("description") or card.get("personality") or ""
    return {
        "identity": {"name": name, "role": role, "description": desc, "tags": []},
        "behavior": {"directives": [], "boundaries": []},
        "communication_style": {"voice": "", "style_notes": []},
        "gait": {"default": "walk"},
        "rhythm": {"default": "flop"},
        "memory": {"mode": "HYBRID"},
        "aperture": {"mode": "balanced"},
        "meta": {"card_spec": "fallback"},
    }, ["card2mpf module unavailable; minimal normalization applied."]


# ════════════════════════════════════════════════════════════════════════════
#  LLM ENHANCEMENT
# ════════════════════════════════════════════════════════════════════════════

_ENHANCEMENT_PROMPT = """\
You are converting a character card into a JL Engine fat-agent MPF payload.

Here is the normalized character data:
{card_json}

Based on this character, generate the following JL MPF fat-agent fields as a valid JSON object.
Fill every field — infer from the character's personality, voice, and backstory if not explicit.

Required output (JSON only, no explanation, no markdown):
{{
  "archetype": "<e.g. sassy_support | stoic_guardian | chaotic_gremlin | wise_mentor>",
  "agent_class": "<mpf:assistant.archetype_snake_case>",
  "sentence_style": "<e.g. punchy and quick | verbose and dramatic | clipped and formal>",
  "tonal_range": ["<tone1>", "<tone2>", "<tone3>"],
  "signature_moves": ["<verbal tic or behavior 1>", "<verbal tic 2>", "<verbal tic 3>"],
  "preferred_gears": ["LITE_REASONING", "TASK_FLOW"],
  "active_modes": ["<mode1>", "<mode2>"],
  "core_directives": ["<directive 1>", "<directive 2>", "<directive 3>", "<directive 4>"],
  "avoidances": ["<avoidance 1>", "<avoidance 2>", "<avoidance 3>"],
  "edge_behavior": "<what the agent does under pressure or uncertainty>",
  "drift_pressure_resistance": <float 0.0-1.0>,
  "emotion_palette": [
    {{"id": "joy", "label": "Joy", "style": "<how this character expresses joy>", "intensity": 0.7}},
    {{"id": "anger", "label": "Anger", "style": "<how this character expresses anger>", "intensity": 0.5}},
    {{"id": "sadness", "label": "Sadness", "style": "<how this character expresses sadness>", "intensity": 0.4}}
  ],
  "short_term_focus": "<what this agent tracks in active memory>",
  "long_term_themes": ["<persistent theme 1>", "<persistent theme 2>"]
}}
"""


def _call_llm(prompt: str, timeout: int = 60) -> str | None:
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(
                f"{ENGINE_BASE}/quest/chat",
                json={"message": prompt, "execution_mode": "chat"},
            )
            r.raise_for_status()
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return (
                data.get("reply") or data.get("response") or
                data.get("message") or data.get("text") or r.text
            )
    except Exception:
        return None


def _extract_json_from_llm(text: str) -> dict | None:
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try stripping markdown fences
    import re
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Try finding first { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def enhance_with_llm(normalized: dict) -> dict:
    """Call the engine LLM to fill in MPF-specific fat-agent fields."""
    card_summary = {
        "name": (normalized.get("identity") or {}).get("name"),
        "role": (normalized.get("identity") or {}).get("role"),
        "description": (normalized.get("identity") or {}).get("description"),
        "voice": (normalized.get("communication_style") or {}).get("voice"),
        "directives": (normalized.get("behavior") or {}).get("directives"),
        "scenario": (normalized.get("behavior") or {}).get("scenario"),
        "emotional_posture": normalized.get("emotional_posture"),
        "tags": (normalized.get("identity") or {}).get("tags"),
    }
    prompt = _ENHANCEMENT_PROMPT.format(card_json=json.dumps(card_summary, indent=2))
    reply = _call_llm(prompt)
    if not reply:
        return {}
    return _extract_json_from_llm(reply) or {}


# ════════════════════════════════════════════════════════════════════════════
#  ASSEMBLY
# ════════════════════════════════════════════════════════════════════════════

def _slugify(name: str) -> str:
    out = []
    for ch in (name or "agent"):
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    return ("".join(out)).strip("_") or "agent"


def assemble_jlmpf(normalized: dict, llm_fields: dict, source_path: str = "") -> dict:
    """Combine normalized card data + LLM-generated fields into a full fat-agent payload."""
    identity = normalized.get("identity") or {}
    behavior = normalized.get("behavior") or {}
    comms = normalized.get("communication_style") or {}
    gait = normalized.get("gait") or {}
    rhythm = normalized.get("rhythm") or {}
    memory = normalized.get("memory") or {}
    aperture = normalized.get("aperture") or {}
    emotional_posture = normalized.get("emotional_posture") or {}

    name = identity.get("name") or "Unnamed Agent"
    role = identity.get("role") or "Agent"

    payload: dict[str, Any] = {
        "name": name,
        "role": role,
        "archetype": llm_fields.get("archetype") or identity.get("archetype") or "assistant",
        "description": identity.get("description") or f"{name} — imported from character card.",
        "tags": identity.get("tags") or [],

        "agent_class": llm_fields.get("agent_class") or f"mpf:assistant.{_slugify(name.lower())}",

        # Behavior
        "core_directives": (
            llm_fields.get("core_directives") or
            behavior.get("directives") or
            ["Maintain consistent characterization.", "Stay in character at all times."]
        ),
        "avoidances": (
            llm_fields.get("avoidances") or
            behavior.get("boundaries") or
            ["Breaking character without reason.", "Ignoring established setting."]
        ),
        "edge_behavior": llm_fields.get("edge_behavior") or "Fall back to core personality.",

        # Gait & rhythm
        "sentence_style": llm_fields.get("sentence_style") or comms.get("voice") or "natural, conversational",
        "tonal_range": llm_fields.get("tonal_range") or ["neutral", "warm", "focused"],
        "signature_moves": llm_fields.get("signature_moves") or [],

        # Cognitive
        "preferred_gears": llm_fields.get("preferred_gears") or ["LITE_REASONING", "TASK_FLOW"],
        "active_modes": llm_fields.get("active_modes") or ["HUMANIZED_EXPLANATION"],

        # Emotion
        "emotion_palette": llm_fields.get("emotion_palette") or [],
        "emotional_posture": emotional_posture,

        # Memory
        "short_term_focus": llm_fields.get("short_term_focus") or "Track recent conversation context.",
        "long_term_themes": llm_fields.get("long_term_themes") or ["user relationship", "role consistency"],

        # Engine
        "drift_pressure_resistance": llm_fields.get("drift_pressure_resistance") or 0.6,
        "gait": gait,
        "rhythm": rhythm,
        "memory": memory,
        "aperture": aperture,

        # LLM profiles passthrough
        "llm_profiles": normalized.get("llm_profiles") or {"generic_llm": {"boot_prompt": ""}},

        # Meta
        "meta": {
            "source_file": source_path,
            "card_spec": (normalized.get("meta") or {}).get("card_spec") or "imported",
            "converted_at": datetime.now(timezone.utc).isoformat(),
            "mpf_spec_version": "1.3.0",
            "converter": "card_converter.py",
            "warnings": (normalized.get("meta") or {}).get("warnings") or [],
        },
    }

    # Pass through any extra engine-specific fields already in the normalized card
    for passthrough in (
        "engine_alignment", "cognitive_gears", "cognitive_modes",
        "operational_behavioral_traits", "flip_flop_modes", "behavioral_core",
    ):
        if passthrough in normalized:
            payload[passthrough] = normalized[passthrough]

    return payload


# ════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

def convert(
    card_path: str | Path,
    output_dir: str | Path | None = None,
    enhance: bool = True,
    force: bool = False,
) -> tuple[Path, dict, list[str]]:
    """
    Convert a card file to a JL MPF fat-agent payload.

    Returns:
        (output_path, payload_dict, warnings)
    """
    card_path = Path(card_path)
    raw_card = load_card(card_path)
    normalized, warnings = _normalize_card(raw_card)

    llm_fields: dict = {}
    if enhance:
        llm_fields = enhance_with_llm(normalized)
        if not llm_fields:
            warnings.append("LLM enhancement failed or engine not running; using card fields only.")

    payload = assemble_jlmpf(normalized, llm_fields, source_path=str(card_path))

    # Determine output path
    name_slug = _slugify((payload.get("identity") or payload).get("name") or card_path.stem)
    if output_dir:
        out_dir = Path(output_dir)
    else:
        # Default: fat_agents directory in the engine root
        out_dir = _ENGINE_ROOT / "jl_engine_core" / "data" / "agents" / "fat_agents"
        if not out_dir.exists():
            out_dir = _ENGINE_ROOT / "jl_engine_core" / "data" / "agents"
        if not out_dir.exists():
            out_dir = card_path.parent

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name_slug}.jlmpf.json"

    if out_path.exists() and not force:
        raise FileExistsError(
            f"Output already exists: {out_path}. Pass force=True to overwrite."
        )

    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return out_path, payload, warnings


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Convert character card to JL MPF format.")
    parser.add_argument("card", help="Path to .png or .json card file.")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory.")
    parser.add_argument("--no-enhance", action="store_true", help="Skip LLM enhancement.")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing output.")
    args = parser.parse_args()

    out_path, payload, warns = convert(
        args.card,
        output_dir=args.output_dir,
        enhance=not args.no_enhance,
        force=args.force,
    )
    print(f"Written: {out_path}")
    if warns:
        print("Warnings:")
        for w in warns:
            print(f"  - {w}")
