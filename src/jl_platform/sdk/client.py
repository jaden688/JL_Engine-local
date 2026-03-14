from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from jl_platform.core.engine import CoreEngine
from jl_platform.core.runtime.app import PlatformApp
from jl_platform.core.util.banner import print_banner_once
from jl_platform.hosts.npc.mapper import NPCHostAdapter

HOST_REGISTRY = {
    "npc": NPCHostAdapter,
}


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
    if host_name not in HOST_REGISTRY:
        raise ValueError(
            f"Unknown host '{host_name}'. Available hosts: {', '.join(sorted(HOST_REGISTRY.keys()))}"
        )
    print_banner_once()
    host_cfg = _load_host_config(config_path)
    adapter_cls = HOST_REGISTRY[host_name]
    adapter = adapter_cls()
    app = PlatformApp(adapter, engine=engine)
    # allow host-specific config injection later
    if host_cfg:
        app.host_context = adapter.build_context(host_cfg, app.registry.list_specs())
    return app
