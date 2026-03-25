from __future__ import annotations

from types import ModuleType

from ._legacy import load_legacy_server


def get_server_module() -> ModuleType:
    """Return the loaded legacy server module."""
    return load_legacy_server()


def create_mcp_server():
    """Return the FastMCP app exposed by the legacy server."""
    return get_server_module().mcp


def run() -> None:
    """Run the MCP server."""
    create_mcp_server().run()
