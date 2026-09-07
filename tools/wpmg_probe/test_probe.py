"""Offline checks for bounded, read-only capture and exception preservation."""

# Standalone tests run without installing pytest or Home Assistant.
# ruff: noqa: PT009, PT027

import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from probe import collect, main, read_one
from pymodbus.exceptions import ModbusException


class ProbeTests(unittest.TestCase):
    """Exercise the actual request path without a network connection."""

    def test_fixed_read_only_survey(self):
        """Only FC04, count one, unit one; both candidate offsets are captured."""
        client = Mock(spec=["read_input_registers"])
        client.read_input_registers.return_value = SimpleNamespace(
            isError=lambda: False, registers=[32768]
        )
        rows = collect(client, pause=lambda _: None)
        self.assertEqual(len(rows), 17)
        self.assertEqual(rows[0]["wire_address"], 5001)
        self.assertEqual(rows[1]["wire_address"], 5999)
        self.assertEqual(rows[9]["wire_address"], 6000)
        self.assertEqual({r["offset"] for r in rows[1:]}, {-1, 0})
        self.assertTrue(all(r["raw_hex"] == "0x8000" for r in rows))
        for call in client.read_input_registers.call_args_list:
            self.assertEqual(call.kwargs, {"count": 1, "device_id": 1})

    def test_exception_does_not_abort_survey(self):
        """The reported illegal address must not hide later successful reads."""
        client = Mock(spec=["read_input_registers"])
        client.read_input_registers.side_effect = [
            SimpleNamespace(isError=lambda: True, exception_code=2),
            *[SimpleNamespace(isError=lambda: False, registers=[1234])] * 16,
        ]
        rows = collect(client, pause=lambda _: None)
        self.assertEqual(rows[0]["exception_code"], 2)
        self.assertEqual(rows[-1]["raw_u16"], 1234)

    def test_transport_error_is_sanitized(self):
        """Library errors must not leak host details into a shared report."""
        client = Mock(spec=["read_input_registers"])
        client.read_input_registers.side_effect = ModbusException("private-host")
        result = read_one(client, 5001)
        self.assertEqual(result["status"], "transport_error")
        self.assertNotIn("private-host", str(result))

    def test_report_and_overwrite_protection(self):
        """Save a shareable report and refuse reuse before opening a connection."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.json"
            with (
                patch(
                    "sys.argv", ["probe.py", "private-host", "--output", str(output)]
                ),
                patch("probe.ModbusTcpClient") as factory,
                patch(
                    "probe.collect", return_value=[{"status": "ok", "raw_u16": 1234}]
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                factory.return_value.connect.return_value = True
                self.assertEqual(main(), 0)
                report = output.read_text()
                self.assertNotIn("private-host", report)
                self.assertEqual(json.loads(report)["results"][0]["raw_u16"], 1234)
                factory.return_value.close.assert_called_once()
                factory.reset_mock()
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    main()
                factory.assert_not_called()
                self.assertEqual(output.read_text(), report)

    def test_connection_failure_still_saves_report(self):
        """Unreachable hardware should produce a useful, sanitized result."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.json"
            with (
                patch(
                    "sys.argv", ["probe.py", "private-host", "--output", str(output)]
                ),
                patch("probe.ModbusTcpClient") as factory,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                factory.return_value.connect.return_value = False
                self.assertEqual(main(), 1)
                self.assertEqual(
                    json.loads(output.read_text())["status"], "connection_failed"
                )
                factory.return_value.read_input_registers.assert_not_called()

    def test_short_response(self):
        """Malformed responses must not be presented as valid values."""
        client = Mock(spec=["read_input_registers"])
        client.read_input_registers.return_value = SimpleNamespace(
            isError=lambda: False, registers=[]
        )
        self.assertEqual(read_one(client, 6000)["status"], "invalid_response")


if __name__ == "__main__":
    unittest.main()
