# WPM G original six-temperature alpha test

For the current source branch, first read the [development dependency gate](wpmg-development.md).
This page preserves the original six-temperature alpha and its display comparison.
The expanded source now includes 149 read-only fields; see
[register coverage](wpmg-register-coverage.md). It is not a packaged alpha release.

This test build is limited to the ISG-connected WPM G route discussed in
[issue #684](https://github.com/pail23/stiebel_eltron_isg_component/issues/684).
It is not for the direct Genesis/display Modbus endpoint discussed separately.

The alpha does not auto-detect WPM G. Select **WPM G (experimental,
read-only)** explicitly during setup. It creates six temperature sensors and
one diagnostic button. It does not load climate, number, select, switch or
binary-sensor platforms and contains no writable WPM G fields.

## Register scope

The manufacturer manual chapter 9, the ISG GENESIS mapping and one hardware
capture agree on the following FC04 input-register conversion. The full Modbus
reference and the printed primary-pump address are one-based; the Wire column
is the zero-based address sent in the request.

| Sensor | Reference | Primary | Wire | Scale | Invalid |
| --- | ---: | ---: | ---: | ---: | --- |
| Brine inlet temperature | 36021 | 6021 | 6020 | 0.01 °C | `0x8000` |
| Brine outlet temperature | 36022 | 6022 | 6021 | 0.01 °C | `0x8000` |
| Condenser inlet temperature | 36024 | 6024 | 6023 | 0.01 °C | `0x8000` |
| Condenser outlet temperature | 36025 | 6025 | 6024 | 0.01 °C | `0x8000` |
| Average outside temperature | 36100 | 6100 | 6099 | 0.01 °C | `0x8000` |
| Weighted DHW temperature | 36101 | 6101 | 6100 | 0.01 °C | `0x8000` |

Temperatures are decoded as signed 16-bit values. The matching GENESIS object
metadata permits negative temperatures, while the hardware capture confirmed
the scale and `0x8000` unavailable marker for this register family.

## Install

1. Keep a copy of the current
   `/config/custom_components/stiebel_eltron_isg` directory if it exists.
2. Extract the test ZIP so its files become the contents of
   `/config/custom_components/stiebel_eltron_isg`.
3. Restart Home Assistant.
4. Add **Stiebel Eltron ISG**, enter the ISG host and port, and select
   **WPM G (experimental, read-only)** as the controller type.

Do not expose Modbus TCP to the internet. No setting on the heat pump needs to
be changed for this test.

## Expected first comparison

The existing capture was taken from a WPE-I 57 Premium H with controller
software 4.00 (003), controller 16.00.099 / firmware 16.00.000 and ISG
12.6.6.0. Its reads and display photos were several minutes apart, so small
temperature movement is expected:

| Sensor | Alpha decode | Later display value |
| --- | ---: | ---: |
| Average outside temperature | 15.00 °C | 15.1 °C |
| Weighted DHW temperature | 55.62 °C | 55.7 °C |
| Brine inlet temperature | 27.91 °C | 28.2 °C |
| Brine outlet temperature | 27.20 °C | 27.2 °C |
| Condenser inlet temperature | 29.43 °C | 29.4 °C flow |
| Condenser outlet temperature | 29.38 °C | 29.4 °C return |

The condenser comparison is plausible, but the display labels are not an exact
terminology match. Treat that pair as a validation target rather than a final
semantic proof.

## Feedback needed

After at least two refreshes, press **Run WPM G diagnostics** once. The button
performs one FC04 read for each of the 163 documented primary-heat-pump input
registers. Unsupported addresses are recorded individually and do not abort
the remaining scan. The scan does not read holding registers and does not
write anything. It normally takes several seconds and stops after three
consecutive communication failures or, at the latest, after two minutes. A
second press while it is running is rejected instead of queuing another scan.

When the button finishes, download the integration diagnostics from Home
Assistant. The WPM G report is kept in memory only and disappears on restart.
Check the JSON before sharing it; Home Assistant redacts the configured ISG
host, and the report itself contains only register addresses, raw values,
timestamps and per-register result status. An interrupted report keeps the
completed rows and marks every unattempted register as skipped.

Also record the six entity values and simultaneous display readings. Report
any unavailable entity, spikes, sign errors or update failures, plus the exact
heat-pump model, controller software and ISG firmware. Do not include the ISG
address, credentials or serial number.

Automatic model detection, room and buffer values, heating-circuit assignment,
secondary heat pumps, counters, status registers and every holding register
remain outside this alpha.

## Roll back

If this was a new experimental entry, remove that entry before downgrading. The controller mode cannot be changed by reconfiguration; host and port can still be updated.
Restore the saved `stiebel_eltron_isg` directory and restart Home Assistant.
No device-side rollback is required because the alpha performs reads only.
