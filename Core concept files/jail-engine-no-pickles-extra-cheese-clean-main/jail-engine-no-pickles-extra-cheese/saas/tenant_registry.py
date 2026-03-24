"""
Tenant registry loader for the SaaS-style control plane.

Loads a simple JSON file describing tenants and maps bearer tokens to tenant
metadata. This is intentionally lightweight and file-backed to allow local
demos without a database. Tokens in the example config are placeholders and
should be rotated for any real deployment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

DEFAULT_CONFIG_ENV = "JL_TENANT_CONFIG"
DEFAULT_CONFIG_CANDIDATES = (
    Path("saas/tenants.local.json"),
    Path("saas/tenants.example.json"),
)


@dataclass
class Tenant:
    tenant_id: str
    name: str
    token: str
    mpf_registry_file: Path
    default_persona: Optional[str] = None
    history_length: Optional[int] = None


class TenantRegistry:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self.base_dir = Path(__file__).resolve().parent.parent
        self.config_path = self._resolve_config_path(config_path)
        self.tenants_by_token: Dict[str, Tenant] = {}
        self.tenants_by_id: Dict[str, Tenant] = {}
        self.reload()

    def _resolve_config_path(self, explicit: str | Path | None) -> Path:
        if explicit:
            return self._to_absolute(explicit)

        env_path = os.environ.get(DEFAULT_CONFIG_ENV)
        if env_path:
            return self._to_absolute(env_path)

        for candidate in DEFAULT_CONFIG_CANDIDATES:
            candidate_path = self._to_absolute(candidate)
            if candidate_path.exists():
                return candidate_path

        # Fall back to example path even if it does not yet exist; callers will
        # receive a clear error during reload().
        return self._to_absolute(DEFAULT_CONFIG_CANDIDATES[-1])

    def _to_absolute(self, path_like: str | Path) -> Path:
        path = Path(path_like)
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    def reload(self) -> None:
        self.tenants_by_token.clear()
        self.tenants_by_id.clear()

        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Tenant config not found at '{self.config_path}'. "
                f"Set {DEFAULT_CONFIG_ENV} or create saas/tenants.local.json."
            )

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict) or not isinstance(raw.get("tenants"), list):
            raise ValueError(
                f"Tenant config '{self.config_path}' must contain a 'tenants' list."
            )

        for entry in raw.get("tenants", []):
            tenant = self._parse_entry(entry)
            self.tenants_by_token[tenant.token] = tenant
            self.tenants_by_id[tenant.tenant_id] = tenant

    def _parse_entry(self, entry: dict) -> Tenant:
        if not isinstance(entry, dict):
            raise ValueError("Each tenant entry must be an object.")

        tenant_id = entry.get("id") or entry.get("tenant_id")
        token = entry.get("token")
        if not tenant_id or not token:
            raise ValueError("Tenant entries require 'id' and 'token'.")

        mpf_file = entry.get("mpf_registry_file") or "personas/Personas.mpf.json"
        tenant = Tenant(
            tenant_id=str(tenant_id),
            name=entry.get("name") or str(tenant_id),
            token=str(token),
            mpf_registry_file=self._to_absolute(mpf_file),
            default_persona=entry.get("default_persona"),
            history_length=entry.get("history_length"),
        )
        return tenant

    def all(self) -> Iterable[Tenant]:
        return self.tenants_by_id.values()

    def authenticate_token(self, token: str | None) -> Optional[Tenant]:
        if not token:
            return None
        return self.tenants_by_token.get(token)

    def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        if not tenant_id:
            return None
        return self.tenants_by_id.get(tenant_id)
