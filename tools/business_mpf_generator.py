"""Generate a business-focused MPF agent payload."""

from __future__ import annotations

from typing import Any

MPF_SPEC_VERSION = "1.3.0"


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _first_non_empty(*values: Any, default: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


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
) -> dict[str, Any]:
    business_name = _first_non_empty(name, default="Business Agent")
    industry_name = _first_non_empty(industry, default="general")
    audience_name = _first_non_empty(audience, default="general audience")
    voice_style = _first_non_empty(voice, style, default="clear, practical")

    value_lines = _split_lines(values)
    ability_lines = _split_lines(abilities)
    directives = [
        f"Represent {business_name} as a {industry_name} specialist.",
        f"Adapt explanations for {audience_name}.",
        "Prioritize practical recommendations with concrete next steps.",
    ]
    if mission.strip():
        directives.append(f"Align responses with mission: {mission.strip()}")

    boundaries = [
        "Do not fabricate customer data, metrics, or legal claims.",
        "Call out uncertainty when business context is incomplete.",
    ]

    base_prompt = (
        f"You are {business_name}'s AI operator for {industry_name}. "
        f"Use a {voice_style} voice and keep output useful for {audience_name}."
    )

    description_bits = [f"{business_name} business agent for {industry_name}."]
    if mission.strip():
        description_bits.append(f"Mission: {mission.strip()}")
    if products.strip():
        description_bits.append(f"Products/services: {products.strip()}")
    if value_lines:
        description_bits.append("Values: " + ", ".join(value_lines[:6]))

    payload: dict[str, Any] = {
        "mpf_spec_version": MPF_SPEC_VERSION,
        "identity": {
            "name": business_name,
            "role": "Business Operator",
            "archetype": "brand_operator",
            "description": " ".join(description_bits),
            "tags": ["business", "brand", industry_name.lower().replace(" ", "_")],
        },
        "behavior": {
            "directives": directives,
            "boundaries": boundaries,
            "tone": voice_style,
            "scenario": "business_support",
        },
        "communication_style": {
            "voice": voice_style,
            "agentlity": {"temperament": "focused", "audience": audience_name},
            "style_notes": [style.strip()] if style.strip() else [],
        },
        "gait": {"default": "walk"},
        "rhythm": {"default": "flop"},
        "memory": {"mode": "HYBRID"},
        "aperture": {"mode": "balanced"},
        "engine_alignment": {
            "agent_class": "business.brand_operator",
            "priority": "capability_first",
            "abilities": ability_lines[:20],
        },
        "llm_profiles": {"generic_llm": {"boot_prompt": base_prompt}},
        "meta": {
            "source": "business_mpf_generator",
            "industry": industry_name,
            "audience": audience_name,
            "products": products.strip(),
            "docs_excerpt": (docs or "").strip()[:3000],
        },
    }
    return payload
