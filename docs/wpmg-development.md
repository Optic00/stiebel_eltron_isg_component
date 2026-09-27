# WPM G development status

This branch depends on the local `pystiebeleltron` WPM G draft. The published
0.8.0 package does not provide `pystiebeleltron.wpmg`. Do not package or install
this branch with the unchanged manifest pin. It is not a new alpha release.

## Release order

1. Review and release the separate library API generated from
   the three `api/wpmg_*.csv` files.
2. Set both integration dependency pins to that actual published version.
3. Test a clean installation without `PYTHONPATH`, including the supported
   Home Assistant minimum and current stable versions.
4. Validate repeated polling and recovery on the ISG-connected test device.
   Check the condenser inlet/outlet meaning against the display labels.

The local integration suite can be run against the library checkout with
`PYTHONPATH=/absolute/path/to/library-checkout python -m pytest` in the HA test
environment. This verifies source compatibility, not package installation.

## Implemented scope

- 55 numeric sensors and 94 status/alarm sensors through a separate library API.
- All 149 unambiguous primary FC04 fields from the manual and diagnostic scan.
  See [register coverage and the 14 excluded addresses](wpmg-register-coverage.md).
- The original six temperature entities keep their keys and default enablement.
  Additional entities are disabled by default; all fields are still polled.
- Explicit experimental WPM G selection; no inferred controller ID.
- Sensor, binary-sensor and diagnostic-button platforms only.
- Address reconfiguration preserves the controller family. To change families,
  remove the existing entry and configure a new one.
- Bounded per-register Code 2 isolation with five-minute retries and no stale
  values; connection/protocol failures still mark the device unavailable.
- Normal-poll diagnostics plus the independent bounded manual FC04 scan.
- Host keys are recursively redacted from the complete diagnostic download,
  including options and nested reports. Still inspect downloads before sharing.

The existing September 9 capture and display comparison remain in
[wpmg-alpha-test.md](wpmg-alpha-test.md). They cover the original six-temperature alpha.
The expanded decoding follows the manual; a successful diagnostic read does not
validate every physical value or status transition. Targeted hardware checks are
still needed for the excluded fields and repeated block polling.
No direct Genesis endpoint, secondary devices, counters, holding registers or
writable controls are included.
