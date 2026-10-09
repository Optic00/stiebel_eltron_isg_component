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

from probe import MAPS, build_requests, collect, main, read_one
from pymodbus.exceptions import ModbusException


def ok(value):
    """Return a successful single-register response."""
    return SimpleNamespace(isError=lambda: False, registers=[value])


def refused():
    """Return an illegal data address response."""
    return SimpleNamespace(isError=lambda: True, exception_code=2)


def client_mock():
    """Return a client that can only read."""
    return Mock(spec=["read_input_registers", "read_holding_registers"])


class ProbeTests(unittest.TestCase):
    """Exercise the actual request path without a network connection."""

    def test_request_plan(self):
        """Every library address once, inputs first, shared ones tagged twice."""
        requests = build_requests()
        self.assertEqual(len(requests), 541)
        self.assertEqual({fc for fc, *_ in requests}, {3, 4})
        self.assertEqual(sum(fc == 4 for fc, *_ in requests), 451)
        self.assertEqual(requests[0][:2], (4, 0))
        self.assertEqual(len({r[:2] for r in requests}), len(requests))
        plan = {r[:2]: r[2] for r in requests}
        self.assertEqual(plan[(3, 1020)], ["lwz"])
        self.assertEqual(plan[(4, 17)], ["lwz"])
        self.assertEqual(plan[(4, 5001)], ["lwz", "wpm"])
        self.assertEqual(plan[(4, 3733)], ["wpm"])
        self.assertNotIn((4, 608), plan)
        self.assertEqual(set(MAPS), {"lwz", "wpm"})

    def test_read_only_single_registers(self):
        """Only FC03/FC04 reads, count one, unit one; nothing else is reachable."""
        client = client_mock()
        client.read_input_registers.return_value = ok(32768)
        client.read_holding_registers.return_value = ok(2)
        rows = collect(client, pause=lambda _: None)
        self.assertEqual(len(rows), 541)
        for call in (
            client.read_input_registers.call_args_list
            + client.read_holding_registers.call_args_list
        ):
            self.assertEqual(call.kwargs, {"count": 1, "device_id": 1})
        self.assertEqual(rows[-1]["raw_u16"], 2)

    def test_modbus_exceptions_do_not_abort_survey(self):
        """A refused map must not hide the other one."""
        client = client_mock()
        client.read_input_registers.return_value = refused()
        client.read_holding_registers.return_value = ok(1)
        rows = collect(client, pause=lambda _: None)
        self.assertEqual(len(rows), 541)
        self.assertEqual(rows[0]["exception_code"], 2)
        self.assertEqual(rows[-1]["raw_u16"], 1)

    def test_stops_after_consecutive_transport_errors(self):
        """An unreachable ISG ends the survey instead of timing out 541 times."""
        client = client_mock()
        client.read_input_registers.side_effect = [
            ok(1),
            OSError(),
            refused(),
            *[OSError()] * 3,
        ]
        rows = collect(client, pause=lambda _: None)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[2]["status"], "modbus_error")
        client.read_holding_registers.assert_not_called()

    def test_transport_error_is_sanitized(self):
        """Library errors must not leak host details into a shared report."""
        client = client_mock()
        client.read_holding_registers.side_effect = ModbusException("private-host")
        result = read_one(client, 3, 1017)
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
                parsed = json.loads(report)
                self.assertEqual(parsed["results"][0]["raw_u16"], 1234)
                self.assertEqual(parsed["status"], "stopped_after_transport_errors")
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
        client = client_mock()
        client.read_input_registers.return_value = SimpleNamespace(
            isError=lambda: False, registers=[]
        )
        self.assertEqual(read_one(client, 4, 17)["status"], "invalid_response")


if __name__ == "__main__":
    unittest.main()
