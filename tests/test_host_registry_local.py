from __future__ import annotations

from jl_platform.sdk.client import HOST_REGISTRY, resolve_host_name
from jl_platform.services.api import main as api_main


def test_public_host_registry_uses_local_name() -> None:
    assert list(HOST_REGISTRY.keys()) == ["my-computer"]
    assert resolve_host_name("my-computer") == "my-computer"
    assert resolve_host_name("npc") == "my-computer"
    assert resolve_host_name("computercontrol") == "my-computer"
    assert resolve_host_name("mycomputer") == "my-computer"


def test_api_host_endpoints_only_expose_the_canonical_host() -> None:
    root = api_main.read_root()
    health = api_main.health()
    hosts = api_main.list_hosts()["hosts"]

    assert root["hosts"] == ["my-computer"]
    assert health["hosts"] == ["my-computer"]
    assert [entry["id"] for entry in hosts] == ["my-computer"]
    assert all(entry["id"] != "npc" for entry in hosts)
