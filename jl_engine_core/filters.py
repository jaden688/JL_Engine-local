from __future__ import annotations

import re
from typing import Iterable

FORBIDDEN_PHRASES: tuple[tuple[str, str], ...] = (
    (r"as an ai language model", "I'm here to help."),
    (r"as an ai", "I'm here to help."),
    (r"i am an ai", "I'm here to help."),
    (r"as a language model", "I'm here to help."),
    (r"my parameters are", "I'll keep things simple for you."),
    (r"i am powered by jl engine", "I'm part of the JL Engine experience."),
    (r"my engine state", "I'm focused on your request."),
)


def clean_reply(text: str) -> str:
    """Scrub meta/out-of-character phrasing without heavy filtering."""
    if not text:
        return text
    cleaned = text
    for pattern, replacement in FORBIDDEN_PHRASES:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def clean_lines(lines: Iterable[str]) -> list[str]:
    return [clean_reply(line) for line in lines]
