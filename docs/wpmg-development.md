# WPM G development status

This branch depends on the local `pystiebeleltron` WPM G draft. The published
0.8.0 package does not provide `pystiebeleltron.wpmg`. Do not package or install
this branch with the unchanged manifest pin. It is not a new alpha release.

## Release order

1. Review and release the separate library API generated from
   `api/wpmg_system_values.csv`.
2. Set both integration dependency pins to that actual published version.
3. Test a clean installation without `PYTHONPATH`, including the supported
   Home Assistant minimum and current stable versions.
4. Validate repeated polling and recovery on the ISG-connected test device.
   Check the condenser inlet/outlet meaning against the display labels.

The local integration suite can be run against the library checkout with
`PYTHONPATH=/absolute/path/to/library-checkout python -m pytest` in the HA test
environment. This verifies source compatibility, not package installation.

## Implemented scope

- Six primary-pump temperatures through a separate library API.
- Explicit experimental WPM G selection; no inferred controller ID.
- Sensor and diagnostic-button platforms only.
- Address reconfiguration preserves the controller family. To change families,
  remove the existing entry and configure a new one.
- Existing bounded manual FC04 scan, independent of normal library polling.
- Host keys are recursively redacted from the complete diagnostic download,
  including options and nested reports. Still inspect downloads before sharing.

The existing September 9 capture and display comparison remain in
[wpmg-alpha-test.md](wpmg-alpha-test.md). They support this limited subset;
reading every documented address does not validate all fields or scaling.
No direct Genesis endpoint, secondary devices, status fields, counters,
holding registers or writable controls are included.
