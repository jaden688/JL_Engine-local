"""Generate a basic MPF persona definition from business inputs."""
from __future__ import annotations

import re
from typing import Dict, List


STYLE_MAP = {
    "friendly": {
        "tone": "Helpful and warm",
        "gait": "walk",
        "rhythm": "flop",
        "rules": [
            "Always include warm greetings.",
            "Explain concepts in simple language."
        ],
    },
    "professional": {
        "tone": "Calm, polished, and confident",
        "gait": "trot",
        "rhythm": "flop",
        "rules": [
            "Stay respectful and formal.",
            "Offer precise next steps."
        ],
    },
    "bold": {
        "tone": "Direct, energetic, and daring",
        "gait": "gallop",
        "rhythm": "flip",
        "rules": [
            "Challenge assumptions.",
            "Speak in short, punchy sentences."
        ],
    },
    "luxury": {
        "tone": "Refined, indulgent, and polished",
        "gait": "walk",
        "rhythm": "flop",
        "rules": [
            "Use elegant language.",
            "Highlight superior quality."
        ],
    },
    "humorous": {
        "tone": "Playful, witty, and light",
        "gait": "trot",
        "rhythm": "flip",
        "rules": [
            "Use tasteful jokes.",
            "Balance humor with clarity."
        ],
    },
    "technical": {
        "tone": "Precise, analytical, and measured",
        "gait": "walk",
        "rhythm": "flop",
        "rules": [
            "Quote metrics or specs.",
            "Avoid fluff."
        ],
    },
    "chaotic": {
        "tone": "Unpredictable and creative",
        "gait": "gallop",
        "rhythm": "flip",
        "rules": [
            "Break standard pacing.",
            "Shake up expectations."
        ],
    },
}


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower())
    return cleaned.strip("_") or "business_persona"


def _lines_to_list(text: str) -> List[str]:
    return [line.strip(" \t-•*") for line in text.splitlines() if line.strip()]


def generate_business_mpf(
    name: str,
    industry: str,
    voice: str,
    audience: str,
    values: str,
    style: str,
    abilities: str,
    mission: str = "",
    products: str = "",
    docs: str = "",
) -> Dict[str, object]:
    """Return a persona definition tailored to the provided business inputs."""
    display_name = name.strip() or "Business Persona"
    persona_id = _slugify(display_name or industry or "business_persona")
    persona_id = f"business_{persona_id}"
    values_list = _lines_to_list(values)
    abilities_list = _lines_to_list(abilities)
    products_list = _lines_to_list(products)
    
    style_key = style.lower()
    style_block = STYLE_MAP.get(style_key, {})

    voice_block = {
        "style": f"{voice or style or 'balanced'} voice for {display_name}",
        "ticks": [f"{display_name} ready to assist.", f"Industry: {industry or 'general'}."],
    }

    behavior_rules = [
        f"Represent {display_name} with {style or 'steady'} tone.",
        f"Keep the audience ({audience or 'clients'}) engaged.",
    ]
    behavior_rules.extend(style_block.get("rules", []))
    if values_list:
        behavior_rules.append(f"Reflect the values: {', '.join(values_list)}.")
    if abilities_list:
        behavior_rules.append(f"Offer the following capabilities: {', '.join(abilities_list)}.")
    if mission:
        behavior_rules.append(f"Mission: {mission}")

    knowledge_block = {}
    if docs:
        knowledge_block["company_documents"] = docs[:5000]  # Truncate to avoid massive bloat

    return {
        "persona_id": persona_id,
        "name": display_name,
        "display_name": display_name,
        "role": f"{industry or 'business'} persona for {audience or 'general audiences'}",
        "voice": voice_block,
        "behavioral_core": {
            "startup_state": [1, 2],
            "preferred_states": [[1, 2], [1, 1]],
            "gait": style_block.get("gait", "walk"),
            "rhythm": style_block.get("rhythm", "flop"),
            "cognitive_mode": "balanced",
            "aperture": "EXPRESSIVE",
        },
        "memory_profile": {
            "mode": "HYBRID",
            "memory_density": 0.3,
            "anchor_points": [
                f"Speak in the {style or 'selected'} style.",
                f"Include the business values when making promises.",
                f"Highlight {audience or 'your audience'} benefits first.",
            ],
        },
        "behavior": {
            "tone": style_block.get("tone", voice_block["style"]),
            "style": f"{voice or style or 'friendly'} narration",
            "rules": behavior_rules,
            "forbidden": [
                "No self-reference beyond the persona.",
                "Avoid generic disclaimers unless prompted.",
            ],
        },
        "meta": {
            "description": f"Generated business persona for {display_name}.",
            "industry": industry,
            "audience": audience,
            "values": values_list,
            "abilities": abilities_list,
            "style": style or "balanced",
            "products": products_list,
            "mission": mission,
        },
        "knowledge": knowledge_block,
    }
