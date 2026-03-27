from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from jl_platform.core.engine import CoreEngine
from jl_platform.core.runtime.app import PlatformApp
from jl_platform.core.util.banner import print_banner_once
from jl_platform.hosts.local.mapper import LocalHostAdapter

HOST_REGISTRY = {
    "my-computer": LocalHostAdapter,
}

HOST_ALIASES = {
    "computercontrol": "my-computer",
    "mycomputer": "my-computer",
    "jl-agent": "my-computer",
    "jlagent": "my-computer",
    "jl_agents": "my-computer",
    "jlagents": "my-computer",
}


def resolve_host_name(host_name: str | None) -> str | None:
    normalized = str(host_name or "").strip().lower()
    if not normalized:
        return None
    if normalized in HOST_REGISTRY:
        return normalized
    alias = HOST_ALIASES.get(normalized)
    if alias in HOST_REGISTRY:
        return alias
    return None


def _load_host_config(config_path: Optional[str]) -> Dict[str, Any]:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Host config not found: {config_path}")
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def start_app(
    host_name: str, config_path: str | None = None, engine: CoreEngine | None = None
) -> PlatformApp:
    resolved_host = resolve_host_name(host_name)
    if resolved_host is None or resolved_host not in HOST_REGISTRY:
        raise ValueError(
            f"Unknown host '{host_name}'. Available hosts: {', '.join(sorted(HOST_REGISTRY.keys()))}"
        )
    print_banner_once()
    host_cfg = _load_host_config(config_path)
    adapter_cls = HOST_REGISTRY[resolved_host]
    adapter = adapter_cls()
    app = PlatformApp(adapter, engine=engine)
    # allow host-specific config injection later
    if host_cfg:
        app.host_context = adapter.build_context(host_cfg, app.registry.list_specs())
    return app
