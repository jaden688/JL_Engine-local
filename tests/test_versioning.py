from __future__ import annotations

from jl_engine_cli.lsp_cli import StdioLspServer
from jl_engine_core import get_version


def test_runtime_version_is_1_0_0() -> None:
    assert get_version() == "1.0.0"


def test_lsp_server_reports_runtime_version(monkeypatch) -> None:
    server = StdioLspServer()
    payloads: list[dict] = []

    monkeypatch.setattr(server, "_write_result", lambda _request_id, result: payloads.append(result))

    server._handle_message({"method": "initialize", "id": 1})

    assert payloads[0]["serverInfo"]["version"] == "1.0.0"
