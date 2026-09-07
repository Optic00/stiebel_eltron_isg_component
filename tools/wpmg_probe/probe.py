#!/usr/bin/env python3
"""One-shot, input-register-only survey of the ISG WPM G primary heat pump."""

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

SOURCE = (
    "https://www.stiebel-eltron.com.au/download/"
    "1685919441_321798-44755-9770_ISG%20Modbus_en.pdf"
)
# Chapter 9, printed pages 40-41. Only primary-pump temperature inputs.
TEMPERATURES = (
    (6000, "room", 10),
    (6001, "buffer", 100),
    (6002, "heating_circuit_1_flow", 100),
    (6021, "brine_inlet", 100),
    (6022, "brine_outlet", 100),
    (6024, "condenser_inlet", 100),
    (6025, "condenser_outlet", 100),
    (6100, "outside_averaged", 100),
)


def read_one(client, address):
    """Keep exceptions per address; never persist exception text or host data."""
    try:
        response = client.read_input_registers(address, count=1, device_id=1)
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


def collect(client, pause=time.sleep):
    """Read the failing identification address and two explicit map candidates."""
    requests = [(5001, None, "existing_detection_probe", None)]
    for offset in (-1, 0):
        requests.extend(
            (address + offset, address, name, factor)
            for address, name, factor in TEMPERATURES
        )
    results = []
    for address, documented, name, factor in requests:
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 (Python 3.10)
            "function_code": 4,
            "wire_address": address,
            "documented_address": documented,
            "offset": None if documented is None else address - documented,
            "candidate_label": name,
            "documented_factor": factor,
            **read_one(client, address),
        }
        # Deliberately no automatic sentinel, signedness or device classification.
        results.append(row)
        pause(0.3)
    return results


def main():
    """Write a local report without overwriting an existing capture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="ISG IP address or hostname on your LAN")
    parser.add_argument("--output", type=Path, default=Path("wpmg-report.json"))
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
        "scope": "ISG WPM G primary pump; candidate mappings, not identification",
        "results": [],
    }
    try:
        if client.connect():
            report["results"] = collect(client)
            report["status"] = "completed"
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
