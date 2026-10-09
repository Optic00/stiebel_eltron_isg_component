# LWZ_R290: register map survey

This standalone probe is for an **ISG-connected controller reported as
`LWZ_R290` (model 551)**. The integration reads that controller through the WPM
register map, which has no ventilation registers. The probe checks which
addresses of the LWZ map (including ventilation) and of the WPM map the ISG
actually answers. It does not change Home Assistant, and no HA files,
dependencies or configuration need changing.

Use a computer with Python 3.10+ that can reach the ISG on your LAN. Download
[probe.py](probe.py) using GitHub's **Download raw file** button into an empty
directory, then run these commands there (Linux/macOS):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pymodbus==3.13.1
.venv/bin/python probe.py YOUR_ISG_IP --output lwz-r290-report.json
```

On Windows use `py -3 -m venv .venv` and `.venv\Scripts\python.exe` for the
remaining commands. Run this outside the Home Assistant container. Do not expose
Modbus to the internet.

The script reads **every address `pystiebeleltron` knows for LWZ and WPM
controllers, one register at a time**: 451 input registers (FC04) and 90 holding
registers (FC03), spaced 0.3 seconds apart, with a three-second timeout and no
retries. It uses TCP port 502 and unit ID 1. It has **no write operations**;
reading a holding register does not change it. A run takes about three minutes
and prints its progress. Home Assistant can keep running.

Single reads are deliberate: a block read can succeed across addresses the ISG
refuses individually, so only single reads show which addresses exist. An
Illegal Data Address response (exception code 2) is a valid result and does not
stop the survey. Only that code means the ISG does not serve an address; other
exception codes and timeouts leave the address undecided. After three consecutive connection failures the survey stops
and saves what it has.

Raw values and Modbus exception codes are kept as they are. A successful read
alone does not prove what an address means, which is why the display comparison
below matters.

Please return:

- `lwz-r290-report.json`, after checking its contents. It contains timestamps and
  raw values, but no target address, serial number or credentials.
- The exact model from the type plate, plus ISG and controller firmware.
- The current fan stages for day, night and manual mode and the outside
  temperature, as shown on the unit's display or in the ISG web interface,
  noted while the script runs.

A report is saved even if the connection fails; exit status 1 means no value was
read successfully. Existing output files are never overwritten.
