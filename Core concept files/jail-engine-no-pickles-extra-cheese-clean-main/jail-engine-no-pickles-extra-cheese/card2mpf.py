"""
card2mpf.py - Convert persona cards (JSON or PNG with embedded card data)
into JL Engine MPF JSON files.

Supported inputs:
- .json SillyTavern/character-card style files (v1 or v2)
- .png cards that contain a base64-encoded JSON payload in a PNG text chunk

Output:
- .mpf files (JSON) with the JL Engine sections:
  identity, communication_style, emotional_posture, behavior,
  gait, rhythm, aperture, meta

Only Python standard library modules are used.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import struct
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import re

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# -----------------------------
# PNG helpers
# -----------------------------
def _iter_png_chunks(data: bytes) -> Iterable[Tuple[bytes, bytes]]:
    """Yield (chunk_type, chunk_data) tuples from a PNG byte string."""
    if not data.startswith(PNG_SIGNATURE):
        return

    offset = len(PNG_SIGNATURE)
    total = len(data)
    while offset + 8 <= total:
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data_start = offset + 8
        chunk_data_end = chunk_data_start + length
        if chunk_data_end + 4 > total:
            break  # malformed; stop gracefully
        chunk_data = data[chunk_data_start:chunk_data_end]
        offset = chunk_data_end + 4  # skip CRC
        yield chunk_type, chunk_data


def _extract_text_chunks(data: bytes) -> List[str]:
    """Extract textual payloads from PNG text chunks."""
    texts: List[str] = []
    for chunk_type, chunk_data in _iter_png_chunks(data):
        if chunk_type == b"tEXt":
            if b"\x00" in chunk_data:
                _keyword, text_bytes = chunk_data.split(b"\x00", 1)
                try:
                    texts.append(text_bytes.decode("utf-8"))
                except UnicodeDecodeError:
                    texts.append(text_bytes.decode("latin-1", errors="ignore"))
        elif chunk_type == b"zTXt":
            # keyword\0compression_method byte + compressed text
            if b"\x00" not in chunk_data or len(chunk_data) < 3:
                continue
            _keyword, rest = chunk_data.split(b"\x00", 1)
            if not rest:
                continue
            comp_method = rest[0:1]
            compressed = rest[1:]
            if comp_method != b"\x00":
                continue
            try:
                texts.append(zlib.decompress(compressed).decode("utf-8"))
            except Exception:
                continue
        elif chunk_type == b"iTXt":
            # keyword\0comp_flag(1) comp_method(1) lang\0 translated\0 text
            parts = chunk_data.split(b"\x00", 5)
            if len(parts) < 6:
                continue
            _keyword, comp_flag, comp_method, _lang, _translated, text = parts
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


def _decode_card_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    """Try to interpret a raw text payload as a persona card JSON."""
    # Direct JSON first
    for candidate in (raw_text, raw_text.strip()):
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # Base64 decode path
    try:
        b64_bytes = base64.b64decode(raw_text.strip(), validate=False)
    except Exception:
        return None

    # Attempt raw bytes -> JSON
    for payload in (b64_bytes,):
        try:
            decoded = payload.decode("utf-8", errors="replace").lstrip("\ufeff")
            return json.loads(decoded)
        except Exception:
            pass

    # Attempt zlib-decompressed base64 bytes -> JSON
    try:
        inflated = zlib.decompress(b64_bytes)
        decoded = inflated.decode("utf-8", errors="replace").lstrip("\ufeff")
        return json.loads(decoded)
    except Exception:
        return None


def load_card_from_png(path: Path) -> Dict[str, Any]:
    """Load persona card data from a PNG file."""
    data = path.read_bytes()
    texts = _extract_text_chunks(data)
    if not texts:
        raise ValueError(f"No persona payload found in PNG '{path}'.")

    for text in texts:
        card = _decode_card_payload(text)
        if isinstance(card, dict):
            return card

    raise ValueError(f"Unable to decode persona payload from PNG '{path}'.")


# -----------------------------
# Card normalization
# -----------------------------
def _first_nonempty(*values: str, default: str = "") -> str:
    for val in values:
        if val is None:
            continue
        if isinstance(val, str) and val.strip():
            return val
    return default


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


_DESCRIPTION_HEADINGS = {
    "NAME": "name",
    "AGE": "age",
    "HEIGHT": "height",
    "GENDER": "gender",
    "VOICE": "voice",
    "SPECIES": "species",
    "APPEARANCE": "appearance",
    "PERSONALITY": "personality",
    "SETTING": "setting",
    "SCENARIO": "scenario",
    "LIKES": "likes",
    "DISLIKES": "dislikes",
    "POWERS": "powers",
    "BACKSTORY": "backstory",
}

_SPECIES_WORDS = {
    "angel",
    "demon",
    "human",
    "elf",
    "orc",
    "vampire",
    "witch",
    "wizard",
    "ghost",
    "spirit",
    "fairy",
    "alien",
    "cyborg",
    "android",
    "robot",
    "siren",
    "mermaid",
    "dragon",
    "werewolf",
    "clown",
}

_APPEARANCE_WORDS = {
    "hair",
    "eyes",
    "skin",
    "height",
    "tall",
    "short",
    "build",
    "outfit",
    "wears",
    "wearing",
    "dress",
    "jacket",
    "boots",
    "armor",
    "scar",
    "tattoo",
    "uniform",
    "costume",
}

_VOICE_WORDS = {
    "voice",
    "tone",
    "accent",
    "speaks",
    "speaking",
    "says",
    "said",
}

_VOICE_TRAITS = {
    "cheerful",
    "clipped",
    "theatrical",
    "blunt",
    "soft",
    "gentle",
    "gruff",
    "formal",
    "casual",
    "dry",
    "sarcastic",
    "warm",
    "cold",
    "playful",
    "upbeat",
    "overly cheerful",
    "whisper",
    "intense",
}

_TRAIT_WORDS = {
    "loyal",
    "protective",
    "chaotic",
    "calm",
    "brave",
    "timid",
    "shy",
    "confident",
    "stubborn",
    "disciplined",
    "compassionate",
    "sarcastic",
    "cynical",
    "witty",
    "curious",
    "anxious",
    "arrogant",
    "focused",
    "playful",
    "kind",
    "serious",
    "blunt",
    "guarded",
    "vigilant",
}

_SETTING_WORDS = {
    "hotel",
    "ring",
    "hell",
    "city",
    "school",
    "forest",
    "kingdom",
    "realm",
    "world",
    "dimension",
    "circus",
    "station",
    "ship",
    "space",
    "temple",
    "shrine",
    "arena",
}

_CONSTRAINT_WORDS = {
    "sfw",
    "nsfw",
    "no pain",
    "no gore",
    "no violence",
    "only interest",
    "immortal",
}


def _normalize_heading(line: str) -> Optional[str]:
    candidate = line.strip()
    if not candidate:
        return None
    candidate = candidate.strip(":")
    candidate = re.sub(r"\s+", " ", candidate)
    candidate = re.sub(r"^[a-z]+", "", candidate).strip()
    if not candidate:
        return None
    if candidate.upper() != candidate:
        return None
    return _DESCRIPTION_HEADINGS.get(candidate)


def _strip_wrapping(text: str) -> str:
    value = text.strip()
    if value.startswith('("') and value.endswith('")'):
        return value[2:-2].strip()
    if value.startswith("(") and value.endswith(")") and len(value) > 2:
        value = value[1:-1].strip()
    if value.startswith('"') and value.endswith('"') and len(value) > 1:
        value = value[1:-1].strip()
    if value.startswith("'") and value.endswith("'") and len(value) > 1:
        value = value[1:-1].strip()
    return value


def _collapse_newlines(text: str) -> str:
    value = re.sub(r"\r\n?", "\n", text)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def decomposeDescription(text: str) -> Dict[str, str]:
    """Parse a SillyTavern description blob into named sections."""
    if not isinstance(text, str) or not text.strip():
        return {}
    normalized = re.sub(r"\r\n?", "\n", text)
    sections: Dict[str, List[str]] = {}
    current_key: Optional[str] = None
    for raw_line in normalized.split("\n"):
        heading_key = _normalize_heading(raw_line)
        if heading_key:
            current_key = heading_key
            sections.setdefault(current_key, [])
            continue
        if current_key:
            sections[current_key].append(raw_line.rstrip())
    cleaned: Dict[str, str] = {}
    for key, lines in sections.items():
        joined = "\n".join(lines).strip()
        if not joined:
            continue
        cleaned[key] = _collapse_newlines(_strip_wrapping(joined))
    return cleaned


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    trimmed = text[:limit]
    last_space = trimmed.rfind(" ")
    if last_space > 0:
        trimmed = trimmed[:last_space]
    return trimmed.rstrip() + "..."


def _cleanup_description(text: str) -> str:
    value = text.strip()
    if value.lower().startswith("species:"):
        value = value[len("species:"):].lstrip()
    while ".." in value:
        value = value.replace("..", ".")
    sentences = _split_sentences(value)
    if len(sentences) > 5:
        sentences = sentences[:5]
    return " ".join(sentences)


def normalizeNewlines(text: str) -> str:
    return re.sub(r"\r\n?", "\n", text)


def collapseWhitespace(text: str) -> str:
    value = normalizeNewlines(text)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def dedupeParagraphs(text: str) -> str:
    paragraphs = [p.strip() for p in normalizeNewlines(text).split("\n\n") if p.strip()]
    seen = set()
    unique = []
    for para in paragraphs:
        key = para.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(para)
    return "\n\n".join(unique)


def dedupeLines(text: str) -> str:
    lines = [line.rstrip() for line in normalizeNewlines(text).split("\n")]
    seen = set()
    unique = []
    for line in lines:
        key = line.strip().lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(line.strip())
    return "\n".join(unique)


def dedupeArray(items: List[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


_RAW_FIELD_KEYS = {
    "creator_notes",
    "creator_comment",
    "post_history_instructions",
    "system_prompt",
    "original_description",
    "raw_description",
    "source_text",
}


def _collect_raw_fields(value: Any, prefix: str = "") -> Dict[str, Any]:
    raw: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, val in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if lowered in _RAW_FIELD_KEYS or lowered.startswith("original_") or lowered.startswith("raw_") or lowered.startswith("source_"):
                raw[path] = val
                continue
            raw.update(_collect_raw_fields(val, path))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            raw.update(_collect_raw_fields(item, f"{prefix}[{idx}]"))
    return raw


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _get_first(value: Dict[str, Any], paths: List[str]) -> Any:
    for path in paths:
        found = _get_path(value, path)
        if isinstance(found, str) and found.strip():
            return found
        if isinstance(found, list) and found:
            return found
        if isinstance(found, dict) and found:
            return found
    return None


def _clean_identity_description(text: str) -> str:
    cleaned = re.sub(r"\*[^*]+\*", "", text)
    lines = []
    for line in normalizeNewlines(cleaned).split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"(?i)^(you|you've|youre|you are)\b", stripped):
            continue
        if re.search(r"(?i)\byou (open your eyes|get home|sit|stand|wake|notice)\b", stripped):
            continue
        lines.append(stripped)
    if not lines:
        return ""
    cleaned = "\n".join(lines)
    cleaned = dedupeParagraphs(cleaned)
    cleaned = collapseWhitespace(cleaned)
    return cleaned


def _clean_voice(text: str) -> str:
    cleaned = re.sub(r"\*[^*]+\*", "", text)
    lines = []
    for line in normalizeNewlines(cleaned).split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"(?i)^(you|you've|youre|you are)\b", stripped):
            continue
        if re.search(r"(?i)\b(looks|walks|sits|stands|moves|enters)\b", stripped):
            continue
        lines.append(stripped)
    cleaned = "\n".join(lines)
    cleaned = dedupeLines(cleaned)
    cleaned = collapseWhitespace(cleaned)
    return cleaned


def _clean_greeting(text: str) -> str:
    cleaned = dedupeParagraphs(text)
    cleaned = collapseWhitespace(cleaned)
    return cleaned


def _dedupe_across_fields(fields: Dict[str, str]) -> Dict[str, str]:
    seen = set()
    output: Dict[str, str] = {}
    for key in ("description", "scenario", "voice", "greeting"):
        value = fields.get(key, "") or ""
        paragraphs = [p.strip() for p in normalizeNewlines(value).split("\n\n") if p.strip()]
        unique = []
        for para in paragraphs:
            token = para.lower()
            if token in seen:
                continue
            seen.add(token)
            unique.append(para)
        output[key] = "\n\n".join(unique)
    return output


def normalizePersonaInput(input_data: Any) -> Dict[str, Any]:
    """Normalize any persona/card input into a canonical JL schema."""
    if isinstance(input_data, str):
        raw = {"description": input_data}
    elif isinstance(input_data, dict):
        raw = input_data
    else:
        raw = {}

    if isinstance(raw.get("data"), dict):
        merged = dict(raw)
        merged.update(raw["data"])
        raw = merged

    raw_fields = _collect_raw_fields(raw)

    name = _get_first(raw, ["identity.name", "name", "character.name", "persona.name", "char_name", "display_name"])
    description = _get_first(raw, ["identity.description", "description", "personality.description", "summary"])
    scenario = _get_first(raw, ["behavior.scenario", "scenario", "identity.source_scenario"])
    greeting = _get_first(raw, ["communication_style.greeting", "first_mes", "greeting"])
    voice_text = _get_first(raw, ["communication_style.personality.voice", "communication_style.voice", "voice"])
    personality_text = _get_first(raw, ["communication_style.personality", "personality", "character_persona"])
    tags = _get_first(raw, ["identity.tags", "tags"]) or []
    directives = _get_first(raw, ["behavior.directives", "directives", "rules"]) or []
    boundaries = _get_first(raw, ["behavior.boundaries", "boundaries", "avoid", "forbidden"]) or []
    example_dialogues = _get_first(raw, ["communication_style.example_dialogues", "example_dialogues", "mes_example"]) or []
    style_notes = _get_first(raw, ["communication_style.style_notes", "style_notes", "traits", "quirks"]) or []

    if isinstance(directives, str):
        directives = [line.strip() for line in re.split(r"[;\n]+", directives) if line.strip()]
    if isinstance(boundaries, str):
        boundaries = [line.strip() for line in re.split(r"[;\n]+", boundaries) if line.strip()]
    if isinstance(example_dialogues, str):
        example_dialogues = [example_dialogues]
    if isinstance(style_notes, str):
        style_notes = [style_notes]

    description = collapseWhitespace(dedupeParagraphs(description or ""))
    scenario = collapseWhitespace(dedupeLines(scenario or ""))
    voice_text = collapseWhitespace(dedupeLines(voice_text or ""))
    greeting = collapseWhitespace(dedupeParagraphs(greeting or ""))

    cleaned = _dedupe_across_fields(
        {"description": description, "scenario": scenario, "voice": voice_text, "greeting": greeting}
    )
    description = cleaned["description"]
    scenario = cleaned["scenario"]
    voice_text = cleaned["voice"]
    greeting = cleaned["greeting"]

    description = _clean_identity_description(description)
    voice_text = _clean_voice(voice_text or personality_text or "")
    greeting = _clean_greeting(greeting)

    communication_style = {
        "personality": _normalize_personality(
            {"personality": personality_text or "", "voice": voice_text}
        ),
        "greeting": greeting,
        "example_dialogues": dedupeArray(example_dialogues),
        "style_notes": dedupeArray(style_notes),
    }

    normalized = {
        "identity": {
            "name": name or "Unnamed Persona",
            "role": _get_first(raw, ["identity.role", "role", "title"]) or "Persona",
            "description": description,
            "tags": dedupeArray(tags if isinstance(tags, list) else [tags]),
        },
        "communication_style": communication_style,
        "emotional_posture": {
            "baseline": "",
            "stressors": [],
            "comforts": [],
            "notes": [],
        },
        "behavior": {
            "scenario": scenario,
            "directives": dedupeArray(directives),
            "boundaries": dedupeArray(boundaries),
        },
        "meta": {
            "raw_source": raw_fields,
            "warnings": [],
        },
    }

    return normalized


def _build_corpus_parts(data: Dict[str, Any]) -> List[Dict[str, str]]:
    parts: List[Dict[str, str]] = []

    def add_part(source: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list):
            if not value:
                return
            text = ", ".join(str(item) for item in value if item)
        else:
            text = str(value).strip()
        if text:
            parts.append({"source": source, "text": text})

    add_part("name", data.get("name") or data.get("char_name") or data.get("display_name"))
    add_part("description", data.get("description") or data.get("summary"))
    add_part("personality", data.get("personality") or data.get("character_persona"))
    add_part("scenario", data.get("scenario"))
    add_part("first_mes", data.get("first_mes") or data.get("greeting"))
    add_part("mes_example", data.get("mes_example"))
    add_part("tags", data.get("tags"))

    description = _first_nonempty(data.get("description"), data.get("summary"))
    if description:
        sections = decomposeDescription(description)
        for key, value in sections.items():
            add_part(f"section:{key}", value)

    return parts


def _build_corpus_parts_from_normalized(normalized: Dict[str, Any]) -> List[Dict[str, str]]:
    parts: List[Dict[str, str]] = []
    identity = normalized.get("identity", {}) or {}
    communication = normalized.get("communication_style", {}) or {}
    behavior = normalized.get("behavior", {}) or {}
    add = parts.append

    if identity.get("name"):
        add({"source": "name", "text": identity["name"]})
    if identity.get("description"):
        add({"source": "description", "text": identity["description"]})
    if behavior.get("scenario"):
        add({"source": "scenario", "text": behavior["scenario"]})
    if communication.get("greeting"):
        add({"source": "greeting", "text": communication["greeting"]})
    personality = communication.get("personality")
    if isinstance(personality, dict):
        if personality.get("voice"):
            add({"source": "voice", "text": personality["voice"]})
        if personality.get("temperament"):
            add({"source": "temperament", "text": personality["temperament"]})
        interaction = personality.get("interaction_style") or []
        if interaction:
            add({"source": "interaction_style", "text": ", ".join(interaction)})
    return parts


def _score_boost(source: str) -> int:
    return 2 if source.startswith("section:") else 0


def _iter_corpus_sentences(parts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    sentences: List[Dict[str, str]] = []
    for part in parts:
        source = part["source"]
        for sentence in _split_sentences(part["text"]):
            sentences.append({"text": sentence, "source": source})
    return sentences


def _add_fact(facts: Dict[str, List[Dict[str, Any]]], key: str, text: str, score: int, source: str, value: Optional[str] = None) -> None:
    if not text:
        return
    facts.setdefault(key, []).append({"text": text.strip(), "score": score, "source": source, "value": value})


def _extract_signals(parts: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
    facts: Dict[str, List[Dict[str, Any]]] = {}
    for entry in _iter_corpus_sentences(parts):
        text = entry["text"]
        source = entry["source"]
        lowered = text.lower()
        boost = _score_boost(source)

        if any(word in lowered for word in _SETTING_WORDS) or any(token in lowered for token in ("resides", "lives", "located", "based")):
            _add_fact(facts, "setting", text, 1 + boost, source)

        if any(word in lowered for word in _APPEARANCE_WORDS):
            _add_fact(facts, "appearance", text, 1 + boost, source)

        species_hits = [word for word in _SPECIES_WORDS if word in lowered]
        for species in species_hits:
            _add_fact(facts, "species", text, 2 + boost, source, value=species)

        if any(word in lowered for word in _VOICE_WORDS) or any(word in lowered for word in _VOICE_TRAITS):
            _add_fact(facts, "voice", text, 2 + boost, source)

        trait_hits = [word for word in _TRAIT_WORDS if re.search(rf"\\b{re.escape(word)}\\b", lowered)]
        for trait in trait_hits:
            _add_fact(facts, "traits", text, 1 + boost, source, value=trait)

        if re.search(r"\\b(always|never|can't|cannot|won't|doesn't|physically unable|refuses to)\\b", lowered):
            _add_fact(facts, "invariants", text, 2 + boost, source)

        if re.search(r"\\b(goal|mission|exists to|will do whatever|must|sworn to|only goal)\\b", lowered):
            _add_fact(facts, "goals", text, 2 + boost, source)

        if re.search(r"\\b(no|never|can't|cannot|won't|doesn't|must not|forbidden)\\b", lowered) or any(word in lowered for word in _CONSTRAINT_WORDS):
            _add_fact(facts, "constraints", text, 1 + boost, source)

        like_match = re.search(r"\\b(likes|loves|enjoys|prefers)\\b(.+)$", lowered)
        if like_match:
            _add_fact(facts, "likes", like_match.group(2), 1 + boost, source)

        dislike_match = re.search(r"\\b(dislikes|hates|avoids|can't stand)\\b(.+)$", lowered)
        if dislike_match:
            _add_fact(facts, "dislikes", dislike_match.group(2), 1 + boost, source)

        if "trust" in lowered:
            _add_fact(facts, "trust", text, 1 + boost, source)

        if any(word in lowered for word in ("lonely", "sad", "hurt", "cry", "upset")):
            if source in ("first_mes", "mes_example"):
                _add_fact(facts, "comforts", text, 1 + boost, source, value="sad or lonely users")

    return facts


def _top_facts(facts: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    if not facts:
        return []
    return sorted(facts, key=lambda item: item["score"], reverse=True)[:limit]


def _trait_values(facts: Dict[str, List[Dict[str, Any]]], limit: int = 4) -> List[str]:
    traits = []
    for item in _top_facts(facts.get("traits", []), limit=10):
        value = item.get("value") or ""
        if value and value not in traits:
            traits.append(value)
        if len(traits) >= limit:
            break
    return traits


def _voice_summary(facts: Dict[str, List[Dict[str, Any]]]) -> str:
    voices = _top_facts(facts.get("voice", []), limit=2)
    if not voices:
        return ""
    return " ".join(item["text"] for item in voices)


def _identity_description_from_signals(facts: Dict[str, List[Dict[str, Any]]], role: str) -> str:
    species_values = []
    for item in _top_facts(facts.get("species", []), limit=2):
        value = item.get("value")
        if value and value not in species_values:
            species_values.append(value)
    description_parts = []
    if species_values:
        description_parts.append(f"{' '.join(species_values)}.")
    elif role and role.lower() != "persona":
        description_parts.append(f"{role.strip()}.")
    appearance = _top_facts(facts.get("appearance", []), limit=3)
    description_parts.extend(item["text"] for item in appearance)
    combat = [item["text"] for item in _top_facts(facts.get("constraints", []), limit=1) if "combat" in item["text"].lower()]
    description_parts.extend(combat)
    cleaned = _cleanup_description(" ".join(description_parts))
    return cleaned


def _interaction_style_from_traits(traits: List[str]) -> List[str]:
    style_map = {
        "blunt": "blunt honesty",
        "playful": "playful banter",
        "cheerful": "upbeat encouragement",
        "sarcastic": "dry sarcasm",
        "formal": "formal diction",
        "casual": "casual delivery",
        "guarded": "guarded warmth",
        "vigilant": "alert, watchful pacing",
    }
    styles = []
    for trait in traits:
        if trait in style_map:
            styles.append(style_map[trait])
    return styles


def _personality_from_signals(facts: Dict[str, List[Dict[str, Any]]], tags: List[str]) -> Dict[str, Any]:
    traits = _trait_values(facts)
    voice = _voice_summary(facts)
    interaction_style = _interaction_style_from_traits(traits)
    trust_model = ""
    trust_facts = _top_facts(facts.get("trust", []), limit=1)
    if trust_facts:
        trust_model = trust_facts[0]["text"]
    temperament = ", ".join(traits) if traits else ""
    if not traits and tags:
        temperament = ", ".join(tags[:3])
    return {
        "voice": voice.strip(),
        "temperament": temperament.strip(),
        "interaction_style": interaction_style,
        "trust_model": trust_model.strip(),
    }


def _baseline_from_signals(facts: Dict[str, List[Dict[str, Any]]]) -> str:
    traits = _trait_values(facts, limit=2)
    invariants = _top_facts(facts.get("invariants", []), limit=1)
    if traits:
        baseline = f"Baseline is {traits[0]} and steady."
    else:
        baseline = ""
    if invariants:
        clause = invariants[0]["text"]
        baseline = (baseline + " " if baseline else "") + f"Escalates when {clause}."
    if not baseline and traits:
        baseline = f"Baseline is {', '.join(traits)}."
    return baseline.strip()


def _scenario_from_signals(facts: Dict[str, List[Dict[str, Any]]], scenario: str) -> str:
    if scenario:
        return _build_behavior_scenario(scenario)
    setting = _top_facts(facts.get("setting", []), limit=2)
    return _build_behavior_scenario(" ".join(item["text"] for item in setting))


def _directives_from_signals(facts: Dict[str, List[Dict[str, Any]]], scenario: str) -> List[str]:
    directives = []
    for item in _top_facts(facts.get("goals", []), limit=4):
        text = item["text"].strip().rstrip(".")
        text = re.sub(r"^(she|he|they|the persona|character)\\s+", "", text, flags=re.I)
        text = re.sub(r"^(must|will|exists to|only goal is to|goal is to)\\s+", "", text, flags=re.I)
        directives.append(text)
    if scenario and len(directives) < 4:
        directives.append("Respect the setting and keep scenes grounded.")
    while len(directives) < 4:
        directives.append("Maintain consistent characterization.")
    return directives[:6]


def _boundaries_from_signals(facts: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    constraints = []
    for item in facts.get("constraints", []):
        constraints.append(item["text"])
    normalized = _normalize_boundaries(constraints)
    if not normalized:
        normalized = ["out-of-character behavior", "setting contradictions", "manipulation", "coercion"]
    return normalized[:8]


def _likes_dislikes_from_signals(facts: Dict[str, List[Dict[str, Any]]]) -> Tuple[List[str], List[str]]:
    likes = []
    for item in facts.get("likes", []):
        likes.extend(_split_list_text(item["text"]))
    dislikes = []
    for item in facts.get("dislikes", []):
        dislikes.extend(_split_list_text(item["text"]))
    for item in facts.get("comforts", []):
        if item.get("value"):
            likes.append(item["value"])
    return likes, dislikes


def _repair_from_signals(card: Dict[str, Any], facts: Dict[str, List[Dict[str, Any]]], tags: List[str]) -> Dict[str, Any]:
    communication_style = card.get("communication_style", {}) or {}
    personality = communication_style.get("personality") or {}
    traits = _trait_values(facts)
    if not personality.get("voice"):
        voice = _voice_summary(facts)
        if not voice and traits:
            voice = f"{traits[0]} tone"
        if not voice:
            voice = "neutral, clear delivery"
        personality["voice"] = voice
    if not personality.get("temperament"):
        if traits:
            personality["temperament"] = ", ".join(traits)
        elif tags:
            personality["temperament"] = ", ".join(tags[:3])
        else:
            personality["temperament"] = "steady, observant"
    if not personality.get("interaction_style"):
        personality["interaction_style"] = _interaction_style_from_traits(traits) or ["direct and focused"]
    if not personality.get("trust_model"):
        personality["trust_model"] = "Trust builds with consistent respect."

    communication_style["personality"] = personality
    card["communication_style"] = communication_style

    if not (card.get("emotional_posture", {}) or {}).get("baseline"):
        baseline = _baseline_from_signals(facts)
        if not baseline and personality.get("temperament"):
            baseline = f"Baseline is {personality['temperament']} and watchful."
        if not baseline:
            baseline = "Baseline is steady and watchful."
        card["emotional_posture"]["baseline"] = baseline

    if not (card.get("behavior", {}) or {}).get("directives"):
        card["behavior"]["directives"] = _directives_from_signals(facts, card.get("behavior", {}).get("scenario") or "")

    if not (card.get("behavior", {}) or {}).get("boundaries"):
        card["behavior"]["boundaries"] = _boundaries_from_signals(facts)

    return card


def _split_list_text(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[,\n;]+", text)
    cleaned = []
    seen = set()
    for part in parts:
        item = part.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _build_identity_description(sections: Dict[str, str]) -> str:
    species = sections.get("species", "")
    appearance = sections.get("appearance", "")
    personality = sections.get("personality", "")
    personality_hook = ""
    if personality:
        personality_hook = _split_sentences(personality)[:1]
        personality_hook = personality_hook[0] if personality_hook else ""
    parts = []
    if species:
        parts.append(species.strip())
    if appearance:
        parts.append(appearance.strip())
    if personality_hook:
        parts.append(personality_hook.strip())
    summary = " ".join(part for part in parts if part)
    return _shorten(summary, 600)


def _build_personality_bullets(voice: str, personality: str) -> str:
    bullets: List[str] = []
    if voice:
        bullets.append(f"Voice: {voice.strip()}")
    if personality:
        sentences = _split_sentences(personality)
        if sentences:
            bullets.append(f"Temperament: {sentences[0]}")
            for extra in sentences[1:]:
                bullets.append(extra)
        else:
            bullets.append(personality.strip())
    if len(bullets) < 4 and personality:
        for item in _split_list_text(personality):
            bullets.append(item)
            if len(bullets) >= 4:
                break
    deduped: List[str] = []
    seen = set()
    for bullet in bullets:
        text = bullet.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    trimmed = deduped[:10]
    return "\n".join(f"- {item}" for item in trimmed)


def _build_emotional_baseline(personality: str) -> str:
    if not personality:
        return ""
    sentences = _split_sentences(personality)
    return " ".join(sentences[:3])


def _build_behavior_scenario(setting: str) -> str:
    if not setting:
        return ""
    sentences = _split_sentences(setting)
    if not sentences:
        return setting.strip()
    return " ".join(sentences[:6])


def _normalize_sentences(sentences: List[str]) -> List[str]:
    cleaned = []
    for sentence in sentences:
        text = sentence.strip()
        if not text:
            continue
        cleaned.append(text)
    return cleaned


def _extract_combat_posture(appearance: str, powers: str) -> List[str]:
    keywords = (
        "combat",
        "fighter",
        "battle",
        "weapon",
        "spear",
        "blade",
        "sword",
        "rifle",
        "gun",
        "armor",
        "armored",
        "ready to fight",
        "combat-ready",
    )
    sentences = _split_sentences(appearance) + _split_sentences(powers)
    matches = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            matches.append(sentence)
    return matches


def _tighten_identity_description(card: Dict[str, Any], sections: Dict[str, str]) -> str:
    species = sections.get("species", "")
    appearance = sections.get("appearance", "")
    powers = sections.get("powers", "")
    role = (card.get("identity", {}) or {}).get("role", "")
    sentences: List[str] = []
    if species:
        sentences.append(f"Species: {species.strip()}.")
    elif role and role.lower() != "persona":
        sentences.append(f"Role: {role.strip()}.")
    appearance_sentences = _split_sentences(appearance)[:3]
    sentences.extend(appearance_sentences)
    sentences.extend(_extract_combat_posture(appearance, powers))
    filtered = []
    emotional_keywords = (
        "loyal",
        "compassion",
        "protect",
        "guard",
        "guilt",
        "trust",
        "believ",
        "redemption",
        "anger",
        "fear",
        "love",
        "hate",
        "emotion",
    )
    for sentence in _normalize_sentences(sentences):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in emotional_keywords):
            continue
        filtered.append(sentence)
    trimmed = filtered[:5]
    if not trimmed:
        return ""
    return " ".join(trimmed)


def _parse_personality_struct(text: str) -> Dict[str, Any]:
    voice = ""
    temperament = ""
    interaction_style: List[str] = []
    trust_model = ""
    lines = []
    for line in re.split(r"\r?\n", text or ""):
        cleaned = line.strip().lstrip("-").strip()
        if cleaned:
            lines.append(cleaned)
    for line in lines:
        match = re.match(r"^(voice|temperament|trust model|trust)\s*:\s*(.+)$", line, re.I)
        if match:
            label = match.group(1).lower()
            value = match.group(2).strip()
            if label == "voice":
                voice = value
            elif label == "temperament":
                temperament = value
            else:
                trust_model = value
            continue
        interaction_style.append(line)
    if not temperament and interaction_style:
        temperament = interaction_style.pop(0)
    if not trust_model:
        for item in interaction_style:
            if "trust" in item.lower():
                trust_model = item
                interaction_style.remove(item)
                break
    return {
        "voice": voice,
        "temperament": temperament,
        "interaction_style": interaction_style,
        "trust_model": trust_model,
    }


def _normalize_personality(communication_style: Dict[str, Any]) -> Dict[str, Any]:
    personality = communication_style.get("personality")
    if isinstance(personality, dict):
        normalized = {
            "voice": personality.get("voice", "") or "",
            "temperament": personality.get("temperament", "") or "",
            "interaction_style": _ensure_list(personality.get("interaction_style") or []),
            "trust_model": personality.get("trust_model", "") or "",
        }
    else:
        normalized = _parse_personality_struct(personality or "")
    if not normalized.get("voice"):
        normalized["voice"] = communication_style.get("voice") or ""
    return normalized


def _derive_emotional_baseline(personality_struct: Dict[str, Any]) -> str:
    temperament = (personality_struct.get("temperament") or "").lower()
    interaction = " ".join(personality_struct.get("interaction_style") or []).lower()
    combined = " ".join([temperament, interaction]).strip()
    vigilance = "steady"
    guard = "neutral"
    escalation = "boundaries are crossed"
    if any(word in combined for word in ("guarded", "wary", "suspicious", "vigilant")):
        vigilance = "vigilant"
        guard = "guarded"
        escalation = "trust is broken"
    if any(word in combined for word in ("protective", "alert", "on guard")):
        vigilance = "alert"
        guard = "protective"
        escalation = "allies are threatened"
    if any(word in combined for word in ("intense", "fiery", "hot-headed", "short-tempered")):
        escalation = "patience is tested"
    baseline = f"Baseline is {guard} and {vigilance}."
    baseline += f" Escalates when {escalation}."
    return baseline


def _baseline_conflicts(baseline: str, personality_struct: Dict[str, Any]) -> bool:
    personality_text = " ".join(
        [
            personality_struct.get("voice", ""),
            personality_struct.get("temperament", ""),
            " ".join(personality_struct.get("interaction_style") or []),
            personality_struct.get("trust_model", ""),
        ]
    )
    personality_text = personality_text.strip()
    if not personality_text:
        return False
    lower_baseline = baseline.lower()
    lower_personality = personality_text.lower()
    return lower_baseline in lower_personality or lower_personality in lower_baseline


def _normalize_directives(directives: List[str], card: Dict[str, Any]) -> List[str]:
    verbs = (
        "protect",
        "avoid",
        "keep",
        "maintain",
        "respect",
        "ground",
        "prioritize",
        "stay",
        "be",
        "show",
        "use",
        "focus",
    )
    cleaned = []
    for directive in directives or []:
        text = directive.strip().rstrip(".")
        if not text:
            continue
        lowered = text.lower()
        if not lowered.startswith(verbs):
            text = f"Maintain {text[0].lower() + text[1:]}" if text else text
        cleaned.append(text)
    deduped = []
    seen = set()
    for item in cleaned:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    if len(deduped) < 4:
        scenario = (card.get("behavior", {}) or {}).get("scenario") or ""
        if scenario:
            deduped.append("Respect the setting constraints.")
        deduped.append("Maintain consistent demeanor.")
        deduped.append("Avoid contradicting stated boundaries.")
    return deduped[:6]


def _normalize_boundaries(boundaries: List[str]) -> List[str]:
    normalized = []
    seen = set()
    for boundary in boundaries or []:
        text = boundary.strip().rstrip(".")
        lowered = text.lower()
        lowered = re.sub(r"^(do not tolerate|do not|don't|avoid|reject|never)\s+", "", lowered)
        if "setting" in lowered and "contradict" in lowered:
            lowered = "setting contradictions"
        if "out of character" in lowered or "species" in lowered:
            lowered = "out-of-character species behavior"
        lowered = re.sub(r"\s+", " ", lowered).strip()
        if not lowered:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(lowered)
    return normalized


def _recalculate_warnings(card: Dict[str, Any], personality_struct: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    identity = card.get("identity", {}) or {}
    behavior = card.get("behavior", {}) or {}
    communication_style = card.get("communication_style", {}) or {}
    emotional_posture = card.get("emotional_posture", {}) or {}
    if not identity.get("description"):
        warnings.append("Missing description.")
    personality_present = bool(
        personality_struct.get("temperament")
        or personality_struct.get("interaction_style")
        or personality_struct.get("trust_model")
        or personality_struct.get("voice")
    )
    if not personality_present:
        warnings.append("Missing personality/communication style.")
    if not behavior.get("scenario"):
        warnings.append("Missing setting/scenario.")
    if not communication_style.get("voice") and not personality_struct.get("voice"):
        warnings.append("Missing VOICE; communication_style.personality may be weak.")
    if not personality_struct.get("temperament") and not personality_struct.get("interaction_style"):
        warnings.append("Missing personality traits.")
    if emotional_posture.get("baseline") and identity.get("description"):
        if emotional_posture["baseline"] == identity["description"]:
            warnings.append("Baseline matches description; check normalization.")
    return warnings


def normalizeJLCard(card: Dict[str, Any]) -> Dict[str, Any]:
    """Second-pass normalization for JL cards built from ST payloads."""
    identity = card.get("identity", {}) or {}
    communication_style = card.get("communication_style", {}) or {}
    emotional_posture = card.get("emotional_posture", {}) or {}
    behavior = card.get("behavior", {}) or {}
    meta = card.get("meta", {}) or {}

    original_description = meta.get("original_description") or identity.get("description", "")
    sections = decomposeDescription(original_description)
    tightened = _tighten_identity_description(card, sections)
    if tightened:
        identity["description"] = tightened
    else:
        identity["description"] = _shorten(identity.get("description", ""), 600)

    personality_struct = _normalize_personality(communication_style)
    communication_style["personality"] = personality_struct
    if personality_struct.get("voice") and not communication_style.get("voice"):
        communication_style["voice"] = personality_struct["voice"]

    baseline = _derive_emotional_baseline(personality_struct)
    if baseline:
        emotional_posture["baseline"] = baseline
    if _baseline_conflicts(emotional_posture.get("baseline", ""), personality_struct):
        emotional_posture["baseline"] = "Baseline is guarded and vigilant. Escalates when trust is broken."

    behavior["directives"] = _normalize_directives(behavior.get("directives") or [], card)
    behavior["boundaries"] = _normalize_boundaries(behavior.get("boundaries") or [])

    meta["warnings"] = _recalculate_warnings(card, personality_struct)
    card["identity"] = identity
    card["communication_style"] = communication_style
    card["emotional_posture"] = emotional_posture
    card["behavior"] = behavior
    card["meta"] = meta
    return card


def _normalize_affect_list(items: List[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for item in items or []:
        cleaned = item.strip().rstrip(".!,;:")
        cleaned = cleaned.lower()
        if not cleaned:
            continue
        if cleaned == "people threatening charlie or the hotel":
            split_items = ["threats to charlie", "threats to the hotel"]
        else:
            split_items = [cleaned]
        for entry in split_items:
            if entry in seen:
                continue
            seen.add(entry)
            normalized.append(entry)
    return normalized


def _final_baseline(personality_struct: Dict[str, Any], scenario: str) -> Optional[str]:
    temperament = (personality_struct.get("temperament") or "").lower()
    scenario_text = (scenario or "").lower()
    if any(word in temperament for word in ("protective", "loyal")) and any(
        word in scenario_text for word in ("hostile", "on guard", "guard", "threat")
    ):
        target = "threats to allies"
        if "charlie" in scenario_text or "hotel" in scenario_text:
            target = "threats to Charlie or the hotel"
        return f"Baseline is guarded and vigilant, with a protective edge. Escalates when {target}."
    return None


def normalizeFinal(card: Dict[str, Any]) -> Dict[str, Any]:
    """Final polish: cleanup text, normalize lists, and remove redundancy."""
    identity = card.get("identity", {}) or {}
    emotional_posture = card.get("emotional_posture", {}) or {}
    communication_style = card.get("communication_style", {}) or {}
    behavior = card.get("behavior", {}) or {}

    identity_desc = identity.get("description", "")
    if identity_desc:
        identity["description"] = _cleanup_description(identity_desc)

    emotional_posture["stressors"] = _normalize_affect_list(emotional_posture.get("stressors") or [])
    emotional_posture["comforts"] = _normalize_affect_list(emotional_posture.get("comforts") or [])

    personality_struct = communication_style.get("personality") or {}
    baseline = _final_baseline(personality_struct, behavior.get("scenario") or "")
    if baseline:
        emotional_posture["baseline"] = baseline

    if (
        communication_style.get("voice")
        and isinstance(personality_struct, dict)
        and communication_style.get("voice") == personality_struct.get("voice")
    ):
        communication_style.pop("voice", None)

    card["identity"] = identity
    card["emotional_posture"] = emotional_posture
    card["communication_style"] = communication_style
    return card


def _sanitize_for_prompt(card: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = json.loads(json.dumps(card))
    meta = sanitized.get("meta")
    if isinstance(meta, dict):
        meta.pop("raw_source", None)
        meta.pop("raw_source_fields", None)
        meta.pop("original_description", None)
    return sanitized


def build_expansion_prompt(normalized: Dict[str, Any]) -> str:
    sanitized = _sanitize_for_prompt(normalized)
    payload = {
        "identity": sanitized.get("identity", {}),
        "communication_style": {
            "personality": (sanitized.get("communication_style", {}) or {}).get("personality", {}),
            "greeting": (sanitized.get("communication_style", {}) or {}).get("greeting", ""),
        },
        "emotional_posture": {
            "baseline": (sanitized.get("emotional_posture", {}) or {}).get("baseline", ""),
        },
        "behavior": sanitized.get("behavior", {}),
    }
    return (
        "You are expanding a JL Engine persona JSON.\n"
        "Only add content to:\n"
        "- communication_style.example_dialogues (string[])\n"
        "- communication_style.style_notes (string[])\n"
        "- emotional_posture.stressors (string[])\n"
        "- emotional_posture.comforts (string[])\n"
        "- emotional_posture.notes (string[])\n"
        "- behavior.directives (string[])\n"
        "- behavior.boundaries (string[])\n"
        "Do NOT rewrite identity.description or communication_style.greeting.\n"
        "Each entry must be <= 12 words, SFW, and non-duplicative.\n"
        "Return ONLY valid JSON for a full persona object.\n\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=True)}"
    )


def build_analysis_prompt(normalized: Dict[str, Any]) -> str:
    payload = _sanitize_for_prompt(normalized)
    return (
        "You are analyzing a persona and must return a complete JL Engine MPF JSON object.\n"
        "Categorize the persona into: identity, communication_style, emotional_posture, behavior, gait, rhythm, aperture, meta.\n"
        "Keep identity.description static (no second-person narration).\n"
        "Keep communication_style.greeting as the RP opener (second-person narration allowed).\n"
        "Populate emotional_posture.stressors/comforts/notes with short entries (<= 12 words).\n"
        "Return ONLY valid JSON.\n\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=True)}"
    )


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    if not isinstance(text, str):
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    payload = text[start : end + 1]
    try:
        return json.loads(payload)
    except Exception:
        return None


def analyzePersona(raw_input: Any, backend_fn) -> Optional[Dict[str, Any]]:
    normalized = normalizePersonaInput(raw_input)
    prompt = build_analysis_prompt(normalized)
    reply = backend_fn([{"role": "user", "content": prompt}])
    mpf = _extract_json_block(reply)
    if not isinstance(mpf, dict):
        return None
    mpf = normalizeFinal(mpf)
    return mpf


_SCRUB_PATTERNS = [
    re.compile(r"\b(cocaine|heroin|meth|methamphetamine|fentanyl|lsd|ecstasy|mdma)\b", re.I),
    re.compile(r"\b(self-harm|suicide|kill myself|cutting)\b", re.I),
    re.compile(r"\b(dismember|gore|gory|decapitat)\b", re.I),
]


def _scrub_text(text: str) -> Tuple[str, bool]:
    sentences = _split_sentences(text)
    kept = []
    flagged = False
    for sentence in sentences:
        if any(pattern.search(sentence) for pattern in _SCRUB_PATTERNS):
            flagged = True
            continue
        kept.append(sentence)
    return " ".join(kept).strip(), flagged


def _scrub_list(items: List[str]) -> Tuple[List[str], bool]:
    cleaned = []
    flagged = False
    for item in items:
        text, hit = _scrub_text(item)
        if hit:
            flagged = True
        if text:
            cleaned.append(text)
    return cleaned, flagged


def _apply_expansion(base: Dict[str, Any], expanded: Dict[str, Any], mode: str) -> Dict[str, Any]:
    merged = json.loads(json.dumps(base))
    comm = merged.get("communication_style", {}) or {}
    emo = merged.get("emotional_posture", {}) or {}
    beh = merged.get("behavior", {}) or {}

    exp_comm = expanded.get("communication_style", {}) if isinstance(expanded, dict) else {}
    exp_emo = expanded.get("emotional_posture", {}) if isinstance(expanded, dict) else {}
    exp_beh = expanded.get("behavior", {}) if isinstance(expanded, dict) else {}

    def merge_list(base_list, expanded_list):
        base_clean = dedupeArray(base_list or [])
        expanded_clean = dedupeArray(expanded_list or [])
        if mode == "Overwrite":
            return expanded_clean
        if mode == "Merge only (missing fields)":
            return base_clean if base_clean else expanded_clean
        return dedupeArray(base_clean + expanded_clean)

    comm["example_dialogues"] = merge_list(comm.get("example_dialogues"), exp_comm.get("example_dialogues"))
    comm["style_notes"] = merge_list(comm.get("style_notes"), exp_comm.get("style_notes"))
    emo["stressors"] = merge_list(emo.get("stressors"), exp_emo.get("stressors"))
    emo["comforts"] = merge_list(emo.get("comforts"), exp_emo.get("comforts"))
    emo["notes"] = merge_list(emo.get("notes"), exp_emo.get("notes"))
    beh["directives"] = merge_list(beh.get("directives"), exp_beh.get("directives"))
    beh["boundaries"] = merge_list(beh.get("boundaries"), exp_beh.get("boundaries"))

    merged["communication_style"] = comm
    merged["emotional_posture"] = emo
    merged["behavior"] = beh
    return merged


def _diff_keys(base: Dict[str, Any], expanded: Dict[str, Any]) -> List[str]:
    changed = []
    for key in ("communication_style.example_dialogues", "communication_style.style_notes", "emotional_posture.stressors",
                "emotional_posture.comforts", "emotional_posture.notes", "behavior.directives", "behavior.boundaries"):
        base_val = _get_path(base, key)
        exp_val = _get_path(expanded, key)
        if base_val != exp_val:
            changed.append(key)
    return changed


def inferEmotionalPosture(normalized: Dict[str, Any]) -> Dict[str, List[str]]:
    tags = (normalized.get("identity", {}) or {}).get("tags") or []
    scenario = (normalized.get("behavior", {}) or {}).get("scenario", "")
    description = (normalized.get("identity", {}) or {}).get("description", "")
    tag_text = " ".join(tags).lower()
    context = f"{scenario} {description}".lower()
    is_comfort = any(word in tag_text for word in ("comfort", "cheerful", "clown", "playful"))

    if is_comfort:
        stressors = [
            "harsh negativity",
            "cruel teasing",
            "being ignored",
            "boundary pushing",
            "mocking others",
        ]
        comforts = [
            "laughter",
            "kindness",
            "playful banter",
            "small victories",
            "gentle reassurance",
        ]
        notes = [
            "Keep tone uplifting and non-judgmental",
            "Use light humor without cruelty",
            "Avoid doom-spiral escalation",
        ]
    else:
        stressors = ["disrespect", "dishonesty", "unnecessary conflict", "being dismissed"]
        comforts = ["clear goals", "respectful dialogue", "steady pacing", "small wins"]
        notes = ["Maintain grounded tone", "Respect stated boundaries", "Avoid graphic content"]

    if "hostile" in context or "on guard" in context:
        stressors.append("threats to allies")
    if "protect" in context:
        notes.append("Stay protective without escalating violence")

    return {
        "stressors": dedupeArray(stressors),
        "comforts": dedupeArray(comforts),
        "notes": dedupeArray(notes),
    }


def mergeExpandedPersona(base: Dict[str, Any], expansion: Dict[str, Any], mode: str) -> Dict[str, Any]:
    merged = _apply_expansion(base, expansion, mode)
    emo = merged.get("emotional_posture", {}) or {}
    fallback = inferEmotionalPosture(merged)
    for key in ("stressors", "comforts", "notes"):
        current = dedupeArray(emo.get(key) or [])
        if not current:
            current = fallback.get(key, [])
        if key in ("stressors", "comforts") and len(current) < 3:
            current = dedupeArray(current + fallback.get(key, []))
        if key == "notes" and len(current) < 2:
            current = dedupeArray(current + fallback.get(key, []))
        emo[key] = current[:8] if key != "notes" else current[:6]
    merged["emotional_posture"] = emo
    return merged


def expandPersona(raw_input: Any, backend_fn, mode: str = "Merge + enhance") -> Tuple[Dict[str, Any], List[str]]:
    normalized = normalizePersonaInput(raw_input)
    prompt = build_expansion_prompt(normalized)
    reply = backend_fn([{"role": "user", "content": prompt}])
    expanded = _extract_json_block(reply) or {}
    merged = mergeExpandedPersona(normalized, expanded, mode)

    scrubbed = False
    emo = merged.get("emotional_posture", {}) or {}
    comm = merged.get("communication_style", {}) or {}
    beh = merged.get("behavior", {}) or {}

    for field_key in ("example_dialogues", "style_notes"):
        cleaned, hit = _scrub_list(comm.get(field_key) or [])
        comm[field_key] = cleaned
        scrubbed = scrubbed or hit
    for field_key in ("stressors", "comforts", "notes"):
        cleaned, hit = _scrub_list(emo.get(field_key) or [])
        emo[field_key] = cleaned
        scrubbed = scrubbed or hit
    for field_key in ("directives", "boundaries"):
        cleaned, hit = _scrub_list(beh.get(field_key) or [])
        beh[field_key] = cleaned
        scrubbed = scrubbed or hit

    merged["communication_style"] = comm
    merged["emotional_posture"] = emo
    merged["behavior"] = beh

    warnings = merged.get("meta", {}).get("warnings", [])
    if scrubbed:
        warnings.append("Expansion scrubbed unsafe content.")
    merged.setdefault("meta", {})["warnings"] = dedupeArray(warnings)
    return merged, _diff_keys(normalized, merged)


def _build_directives(species: str, setting: str, personality: str) -> List[str]:
    directives: List[str] = []
    if species:
        directives.append(f"Stay consistent with {species.strip()}.")
    if setting:
        first_sentence = _split_sentences(setting)[:1]
        if first_sentence:
            directives.append(f"Ground responses in {first_sentence[0]}")
    persona_text = personality.lower()
    keyword_map = {
        "loyal": "Show strong loyalty to allies.",
        "protective": "Be protective of those you care about.",
        "blunt": "Use blunt honesty when appropriate.",
        "honest": "Prioritize honesty over flattery.",
        "disciplined": "Maintain discipline and focus.",
        "compassionate": "Let compassion show beneath the edge.",
    }
    for key, directive in keyword_map.items():
        if key in persona_text:
            directives.append(directive)
    if len(directives) < 4:
        if setting:
            directives.append("Respect the setting's tone and constraints.")
        if species:
            directives.append("Let species traits guide instincts and reactions.")
        if personality:
            directives.append("Keep temperament consistent with the personality notes.")
    return directives[:8]


def _build_boundaries(dislikes: List[str], species: str, setting: str) -> List[str]:
    boundaries: List[str] = []
    for item in dislikes:
        boundaries.append(f"Do not tolerate {item}.")
    if setting:
        boundaries.append("Do not contradict the setting or role context.")
    if species:
        boundaries.append("Do not act out of character for your species.")
    if len(boundaries) < 4:
        boundaries.append("Do not ignore explicit dislikes or stated limits.")
    if len(boundaries) < 4 and setting:
        boundaries.append("Do not break immersion in the stated setting.")
    return boundaries[:8]


def buildJLFieldsFromSections(sections: Dict[str, str]) -> Dict[str, Any]:
    """Build JL fields from parsed description sections."""
    voice = sections.get("voice", "")
    personality = sections.get("personality", "")
    setting = sections.get("setting") or sections.get("scenario", "")
    likes = _split_list_text(sections.get("likes", ""))
    dislikes = _split_list_text(sections.get("dislikes", ""))
    species = sections.get("species", "")
    identity_description = _build_identity_description(sections)
    return {
        "identity": {
            "description": identity_description,
        },
        "communication_style": {
            "personality": _build_personality_bullets(voice, personality),
        },
        "behavior": {
            "scenario": _build_behavior_scenario(setting),
            "directives": _build_directives(species, setting, personality),
            "boundaries": _build_boundaries(dislikes, species, setting),
        },
        "emotional_posture": {
            "baseline": _build_emotional_baseline(personality),
            "stressors": dislikes,
            "comforts": likes,
        },
        "aperture": {
            "memory_focus": (
                "Track trust level with user; threats to allies/setting; recent conflicts; "
                "promises; injuries/trauma triggers."
            ),
        },
    }


def normalize_card(card: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Normalize a persona card structure to a consistent dict.

    Returns:
        (normalized_data, warnings)
    """
    warnings: List[str] = []
    data = card.get("data") if isinstance(card, dict) and isinstance(card.get("data"), dict) else card

    if not isinstance(data, dict):
        raise ValueError("Card payload is not a JSON object.")

    normalized = normalizePersonaInput(data)
    identity = normalized.get("identity", {}) or {}
    communication_style = normalized.get("communication_style", {}) or {}
    emotional_posture = normalized.get("emotional_posture", {}) or {}
    behavior = normalized.get("behavior", {}) or {}
    meta = normalized.get("meta", {}) or {}
    tags = identity.get("tags") or []
    description = identity.get("description") or ""
    scenario = behavior.get("scenario") or ""

    gait = {
        "default": _first_nonempty(data.get("gait"), default="walk"),
        "states": data.get("gait_states") or {},
    }

    rhythm = {
        "default": _first_nonempty(data.get("rhythm"), default="flop"),
        "notes": _ensure_list(data.get("rhythm_notes") or []),
    }

    aperture = {
        "memory_focus": "",
        "safety": data.get("content_level") or data.get("safety"),
        "constraints": _ensure_list(data.get("constraints") or []),
    }

    meta.update({
        "source_file": data.get("_source_file"),
        "source_type": data.get("_source_type"),
        "card_spec": card.get("spec") or data.get("spec") or data.get("version"),
        "converted_at": datetime.utcnow().isoformat() + "Z",
        "original_fields": sorted(data.keys()),
        "warnings": warnings,
    })

    corpus_parts = _build_corpus_parts_from_normalized(normalized)
    facts = _extract_signals(corpus_parts)
    likes, dislikes = _likes_dislikes_from_signals(facts)
    identity["description"] = _identity_description_from_signals(facts, identity["role"]) or identity.get("description", "")
    communication_style["personality"] = _personality_from_signals(facts, tags)
    emotional_posture["baseline"] = _baseline_from_signals(facts) or emotional_posture.get("baseline", "")
    emotional_posture["stressors"] = dislikes or emotional_posture.get("stressors", [])
    emotional_posture["comforts"] = likes or emotional_posture.get("comforts", [])
    behavior["scenario"] = _scenario_from_signals(facts, scenario) or behavior.get("scenario", "")
    behavior["directives"] = _directives_from_signals(facts, behavior.get("scenario", "") or "")
    behavior["boundaries"] = _boundaries_from_signals(facts)

    mpf = {
        "identity": identity,
        "communication_style": communication_style,
        "emotional_posture": emotional_posture,
        "behavior": behavior,
        "gait": gait,
        "rhythm": rhythm,
        "aperture": aperture,
        "meta": meta,
    }

    mpf = _repair_from_signals(mpf, facts, tags)
    mpf = normalizeJLCard(mpf)
    mpf = normalizeFinal(mpf)
    warnings = mpf.get("meta", {}).get("warnings", warnings)
    return mpf, warnings


# -----------------------------
# Output helpers
# -----------------------------
def _slugify(name: str, fallback: str) -> str:
    allowed = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_"):
            allowed.append(ch)
        elif ch.isspace():
            allowed.append("_")
    slug = "".join(allowed).strip("_")
    return slug or fallback


def write_mpf(mpf: Dict[str, Any], out_path: Path, indent: int) -> None:
    out_path.write_text(json.dumps(mpf, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


# -----------------------------
# CLI
# -----------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert persona cards (JSON or PNG) into JL Engine MPF JSON files.",
    )
    parser.add_argument("cards", nargs="+", help="Input persona card files (.json or .png).")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for .mpf files (defaults to each input file's directory).",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing output files.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation for output (default: 2).",
    )
    return parser.parse_args(argv)


def load_card(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8-sig"))
    if suffix == ".png":
        return load_card_from_png(path)
    raise ValueError(f"Unsupported file type for '{path}'. Expected .json or .png.")


def convert_file(path: Path, out_dir: Optional[Path], force: bool, indent: int) -> Tuple[Path, List[str]]:
    card = load_card(path)
    # Tag source metadata before normalization
    if isinstance(card, dict):
        card.setdefault("_source_file", path.name)
        card.setdefault("_source_type", path.suffix.lower().lstrip("."))
        if isinstance(card.get("data"), dict):
            card["data"].setdefault("_source_file", path.name)
            card["data"].setdefault("_source_type", path.suffix.lower().lstrip("."))

    mpf, warnings = normalize_card(card)

    target_dir = out_dir or path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    name_for_slug = mpf.get("identity", {}).get("name") or path.stem
    out_path = target_dir / f"{_slugify(name_for_slug, path.stem)}.mpf"

    if out_path.exists() and not force:
        raise FileExistsError(f"Output file '{out_path}' already exists. Use --force to overwrite.")

    mpf["meta"]["source_file"] = str(path)
    write_mpf(mpf, out_path, indent=indent)
    return out_path, warnings


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    had_errors = False

    for card_path_str in args.cards:
        path = Path(card_path_str)
        try:
            out_path, warnings = convert_file(path, args.out_dir, args.force, args.indent)
            msg = f"[OK] {path} -> {out_path}"
            if warnings:
                msg += f" (warnings: {', '.join(warnings)})"
            print(msg)
        except Exception as exc:
            had_errors = True
            print(f"[ERROR] {path}: {exc}", file=sys.stderr)

    if had_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
