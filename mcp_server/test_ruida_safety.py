import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcp_server import server
from mcp_server.server import ruida_send_job, run_turn


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.writes = []
        self.rts = False
        self.dtr = False

    def write(self, payload):
        self.writes.append(payload)

    def read(self, size):
        return b""

    def close(self):
        pass


class RuidaSafetyTests(unittest.TestCase):
    def test_rejects_unsafe_or_invalid_parameters_before_serial_access(self):
        for args in (
            {"power_pct": 61},
            {"power_pct": -1},
            {"speed_mm_s": 0},
            {"width_mm": 0},
            {"origin_x_mm": -1},
            {"height_mm": float("nan")},
            {"shape": "unknown"},
            {"auto_start": "yes"},
        ):
            with self.subTest(args=args):
                result = json.loads(ruida_send_job(**args))
                self.assertIn("error", result)

    def test_upload_does_not_start_job_by_default(self):
        serial_instance = FakeSerial()
        fake_serial_module = SimpleNamespace(Serial=lambda *args, **kwargs: serial_instance)
        with patch.dict(sys.modules, {"serial": fake_serial_module}), patch("time.sleep"):
            result = json.loads(ruida_send_job())

        self.assertFalse(result["auto_started"])
        self.assertEqual(len(serial_instance.writes), 1)

    def test_run_turn_forwards_a2a_credentials(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({
            "result": {"history": [{"role": "ROLE_AGENT", "parts": [{"text": "ok"}]}]}
        }).encode()

        with patch.dict(os.environ, {"A2A_API_KEY": "test-key"}), patch(
            "urllib.request.urlopen", return_value=response
        ) as urlopen:
            self.assertEqual(run_turn("hello"), "ok")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_registry_uses_runtime_state_directory(self):
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.object(server, "STATE_DIR", Path(state_dir)):
                registry_path = server.STATE_DIR / "dynamic_tools_registry.json"
                registry_path.write_text('{"tool": "runtime"}', encoding="utf-8")
                self.assertEqual(
                    json.loads(server.list_forged_tools_registry()),
                    {"tool": "runtime"},
                )


if __name__ == "__main__":
    unittest.main()
