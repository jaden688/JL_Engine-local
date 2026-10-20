from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


_ALIASES = {
    "MIT LICENSE": "MIT",
    "APACHE LICENSE 2.0": "APACHE-2.0",
    "APACHE 2.0": "APACHE-2.0",
    "GNU GENERAL PUBLIC LICENSE V3.0": "GPL-3.0",
    "GNU GENERAL PUBLIC LICENSE V2.0": "GPL-2.0",
    "GNU AFFERO GENERAL PUBLIC LICENSE V3.0": "AGPL-3.0",
    "GNU LESSER GENERAL PUBLIC LICENSE V3.0": "LGPL-3.0",
    "BSD 2-CLAUSE": "BSD-2-CLAUSE",
    "BSD 3-CLAUSE": "BSD-3-CLAUSE",
    "THE UNLICENSE": "UNLICENSE",
}


@dataclass(frozen=True, slots=True)
class LicenseVerdict:
    raw: str
    normalized: str
    allowed: bool
    category: str
    reason: str


class LicenseGate:
    DEFAULT_ALLOWED = frozenset(
        {"MIT", "APACHE-2.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "ISC", "UNLICENSE", "MPL-2.0"}
    )
    DEFAULT_BLOCKED_PREFIXES = ("GPL", "AGPL", "LGPL", "CC-BY-SA")

    def __init__(
        self,
        *,
        allowed: Iterable[str] | None = None,
        blocked_prefixes: Iterable[str] | None = None,
        unknown_policy: str = "review",
    ) -> None:
        self.allowed = {self.normalize(item) for item in (allowed or self.DEFAULT_ALLOWED)}
        self.blocked_prefixes = tuple(blocked_prefixes or self.DEFAULT_BLOCKED_PREFIXES)
        self.unknown_policy = unknown_policy

    @staticmethod
    def normalize(value: str | None) -> str:
        text = (value or "").strip()
        if not text:
            return "UNKNOWN"
        upper = " ".join(text.upper().replace("_", "-").split())
        return _ALIASES.get(upper, upper)

    def classify(self, value: str | None) -> LicenseVerdict:
        normalized = self.normalize(value)
        raw = (value or "").strip()
        if normalized in self.allowed:
            return LicenseVerdict(raw, normalized, True, "permissive", f"{normalized} is allowed.")
        if any(normalized.startswith(prefix) for prefix in self.blocked_prefixes):
            return LicenseVerdict(
                raw, normalized, False, "copyleft", f"{normalized} is blocked for source reuse."
            )
        if normalized == "UNKNOWN":
            allowed = self.unknown_policy == "allow"
            return LicenseVerdict(
                raw, normalized, allowed, "unknown", "License is missing or unknown."
            )
        allowed = self.unknown_policy == "allow"
        return LicenseVerdict(
            raw, normalized, allowed, "review", f"{normalized} requires review."
        )
