from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from jl_engine_core import __version__


class StdioLspServer:
    def __init__(self) -> None:
        self._shutdown_requested = False
        self._exit_requested = False

    def run(self) -> int:
        while not self._exit_requested:
            payload = self._read_message()
            if payload is None:
                break
            self._handle_message(payload)
        return 0 if self._shutdown_requested else 1

    def _read_message(self) -> dict[str, Any] | None:
        content_length = None

        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            stripped = line.strip()
            if not stripped:
                break
            if line.lower().startswith(b"content-length:"):
                try:
                    content_length = int(line.split(b":", 1)[1].strip())
                except Exception:
                    return None

        if content_length is None or content_length < 0:
            return None

        body = sys.stdin.buffer.read(content_length)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def _write(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()

    def _write_result(self, request_id: Any, result: Any) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _write_error(self, request_id: Any, code: int, message: str) -> None:
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    def _handle_message(self, payload: dict[str, Any]) -> None:
        method = payload.get("method")
        request_id = payload.get("id")

        if method == "initialize":
            self._write_result(
                request_id,
                {
                    "capabilities": {
                        "textDocumentSync": 1,
                    },
                    "serverInfo": {"name": "CLI", "version": __version__},
                },
            )
            return

        if method == "shutdown":
            self._shutdown_requested = True
            self._write_result(request_id, None)
            return

        if method == "exit":
            self._exit_requested = True
            return

        # Notification: no id means no response required.
        if request_id is None:
            return

        self._write_error(request_id, -32601, f"Method not found: {method}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli",
        description="Language Server Protocol server over stdio (server name: CLI).",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        default=True,
        help="Run as stdio JSON-RPC server (default).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ = build_parser().parse_args(argv)
    return StdioLspServer().run()


if __name__ == "__main__":
    raise SystemExit(main())
