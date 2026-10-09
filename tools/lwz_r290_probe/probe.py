#!/usr/bin/env python3
"""One-shot, read-only survey of the LWZ and WPM register maps on an LWZ_R290 ISG."""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time

from pymodbus import __version__
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

SOURCE = "pystiebeleltron 0.9.1, lwz.py and wpm.py register ranges (wire addresses)"
# Copied verbatim from pystiebeleltron 0.9.1. The WPM 3 and WPM 3i maps are
# subsets of the WPM map, so these two cover every address the library knows.
MAPS = {
    "lwz": {
        3: ((1000, 1026), (4000, 4002), (4249, 4251), (4253, 4258), (4271, 4277)),
        4: (
            (0, 33),
            (2000, 2004),
            (3000, 3031),
            (3679, 3679),
            (3689, 3697),
            (5000, 5001),
            (5219, 5221),
            (5229, 5230),
        ),
    },
    "wpm": {
        3: (
            (1500, 1520),
            (1550, 1558),
            (1603, 1607),
            (1703, 1708),
            (1749, 1751),
            (4000, 4002),
            (4249, 4251),
            (4253, 4255),
            (4257, 4258),
            (4271, 4277),
        ),
        4: (
            (500, 607),
            (609, 610),
            (2500, 2546),
            (2560, 2565),
            (2569, 2572),
            (3500, 3654),
            (3679, 3684),
            (3689, 3733),
            (5000, 5001),
            (5219, 5221),
            (5229, 5230),
        ),
    },
}
# Stop early when the ISG stops answering at all; Modbus exceptions don't count.
MAX_CONSECUTIVE_TRANSPORT_ERRORS = 3


def build_requests():
    """Return (function code, wire address, maps) once per address, inputs first."""
    owners = {}
    for name, spaces in MAPS.items():
        for function_code, ranges in spaces.items():
            for first, last in ranges:
                for address in range(first, last + 1):
                    owners.setdefault((function_code, address), []).append(name)
    return [
        (function_code, address, owners[(function_code, address)])
        for function_code, address in sorted(owners, key=lambda k: (-k[0], k[1]))
    ]


def read_one(client, function_code, address):
    """Keep exceptions per address; never persist exception text or host data."""
    read = (
        client.read_input_registers
        if function_code == 4
        else client.read_holding_registers
    )
    try:
        response = read(address, count=1, device_id=1)
    except (ModbusException, OSError) as err:
        return {"status": "transport_error", "error_type": type(err).__name__}
    if response.isError():
        return {
            "status": "modbus_error",
            "exception_code": getattr(response, "exception_code", None),
        }
    if len(response.registers) != 1:
        return {"status": "invalid_response"}
    raw = response.registers[0]
    return {"status": "ok", "raw_u16": raw, "raw_hex": f"0x{raw:04X}"}


def collect(client, pause=time.sleep, progress=None):
    """Read each address on its own; a block read can mask refused addresses."""
    requests = build_requests()
    results = []
    failures = 0
    for index, (function_code, address, maps) in enumerate(requests, 1):
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 (Python 3.10)
            "function_code": function_code,
            "wire_address": address,
            "maps": maps,
            **read_one(client, function_code, address),
        }
        # Deliberately no automatic sentinel, signedness or device classification.
        results.append(row)
        failures = failures + 1 if row["status"] == "transport_error" else 0
        if progress:
            progress(index, len(requests))
        if failures >= MAX_CONSECUTIVE_TRANSPORT_ERRORS:
            break
        pause(0.3)
    return results


def main():
    """Write a local report without overwriting an existing capture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="ISG IP address or hostname on your LAN")
    parser.add_argument("--output", type=Path, default=Path("lwz-r290-report.json"))
    args = parser.parse_args()
    logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
    # Exclusive creation happens before contacting hardware.
    try:
        output = args.output.open("x", encoding="utf-8")
    except OSError:
        parser.error("Cannot create report. Choose a new writable --output path.")
    client = ModbusTcpClient(args.host, port=502, timeout=3, retries=0)
    report = {
        "format_version": 1,
        "source": SOURCE,
        "pymodbus_version": __version__,
        "unit_id": 1,
        "port": 502,
        "scope": "LWZ_R290 (551); every LWZ and WPM library address, read singly",
        "results": [],
    }

    def progress(done, total):
        if done % 50 == 0 or done == total:
            sys.stdout.write(f"{done}/{total} registers read\n")
            sys.stdout.flush()

    try:
        if client.connect():
            report["results"] = collect(client, progress=progress)
            planned = len(build_requests())
            report["status"] = (
                "completed"
                if len(report["results"]) == planned
                else "stopped_after_transport_errors"
            )
        else:
            report["status"] = "connection_failed"
    except (OSError, ModbusException) as err:
        report["status"] = "transport_error"
        report["error_type"] = type(err).__name__
    finally:
        client.close()
        with output:
            json.dump(report, output, indent=2)
            output.write("\n")
    sys.stdout.write(f"Report saved to {args.output}\n")
    return 0 if any(r["status"] == "ok" for r in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
