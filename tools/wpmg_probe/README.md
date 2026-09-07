# WPM G: first hardware capture

This standalone probe is for an **ISG-connected WPM G**, initially the primary
WPE-I 33-87 H 400 Premium. It does not add Home Assistant support. No HA files,
dependencies or configuration need changing. It is not a probe for the direct
Genesis/display endpoint.

Use a computer with Python 3.10+ that can reach the ISG on your LAN. Download
[probe.py](probe.py) using GitHub's **Download raw file** button into an empty
directory, then run these commands there (Linux/macOS):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pymodbus==3.13.1
.venv/bin/python probe.py YOUR_ISG_IP --output wpmg-report.json
```

On Windows use `py -3 -m venv .venv` and `.venv\Scripts\python.exe` for the
remaining commands. Run this outside the Home Assistant container. No repository
checkout or Home Assistant installation is needed. Do not expose Modbus to the
internet.

The script performs **17 individual FC04 reads**, spaced 0.3 seconds apart,
with a three-second timeout and no retries. It uses TCP port 502 and unit ID 1,
matching the reported connection. It has no write operations and does not scan
the network. Allow about one minute if requests time out. If the same ISG is
already being polled by another tool, pause that polling during the capture.

It records the existing controller-detection request at wire address 5001,
then eight documented temperature inputs at offsets -1 and 0. Both variants
are included because the manufacturer's address convention needs confirming
against this installation. A successful read alone does **not** identify WPM G
or prove the label for that address.

The source is [the manufacturer's ISG Modbus manual, chapter 9, printed pages
40–41](https://www.stiebel-eltron.com.au/download/1685919441_321798-44755-9770_ISG%20Modbus_en.pdf).
Raw values and exception codes are retained without interpreting signedness or
unavailable-value sentinels. This first capture deliberately omits holding
registers, secondary pumps and cumulative counters.

Please return:

- `wpmg-report.json`, after checking its contents. It contains timestamps and raw
  heating values, but no target address, serial number or credentials.
- The exact heat-pump model, ISG model/firmware and controller firmware. The
  integration version `2026.8` is a separate version from ISG firmware.
- Display readings taken during the capture: averaged outside temperature,
  buffer temperature, heating circuit 1 flow, and brine inlet/outlet where
  available. Say which readings are unavailable. No settings need changing.

An Illegal Data Address response at 5001 is expected from the reported failure
and does not stop the remaining reads. Other unsupported inputs are also retained
as individual errors. A report is saved even if connection fails; exit status 1
means no successful values were collected. Existing output files are never
overwritten. For a later capture use another `--output` filename.

Next we compare the raw results with the display, settle addressing/scaling and
available fields, and prepare a small library implementation. A Home Assistant
test version follows once detection and the initial sensor mapping are supported
by these captures. No automatic device classification is inferred from exceptions.
