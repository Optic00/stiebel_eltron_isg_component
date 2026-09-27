# WPM G alpha3 hardware test

For an ISG-connected WPM G only. This build requires Home Assistant 2026.9.0
or 2026.9.3 and an internet connection for automatic dependency installation.
It never writes WPM G registers and does not support the direct Genesis port.

## Install and roll back

1. Back up `/config/custom_components/stiebel_eltron_isg`.
2. Replace its contents with `stiebel_eltron_isg.zip` from the alpha3 release.
3. Restart Home Assistant. The matching library installs automatically.
4. Keep an existing WPM G entry. For a new entry, explicitly select
   **WPM G (experimental, read-only)**.
5. Enable any of the additional numeric/status entities you want to compare.
   The original six temperatures remain enabled by default.

To roll back, restore the backed-up directory and restart Home Assistant.
The original integration's pinned library version will be restored automatically.
Keep the backup until testing is complete. Do not replace library files manually.

## What to check

- Confirm regular values update across several refreshes.
- Compare a few added values with the controller display, including any that
  look implausible. Temperature drift between screenshots is expected.
- Press **Run WPM G diagnostics** once and wait for completion. Normal polling
  waits while this bounded scan runs. The button also releases temporary retry
  exclusions for the next poll.
- Download integration diagnostics, inspect them for private information, and
  attach them to issue #684. `wpmg_polling` explains register failures, raw values,
  retry state and poll duration; `wpmg_diagnostic` contains the separate full scan.
- Report whether values remain usable after a few hours and after an ordinary
  Home Assistant restart. No heat-pump restart or setting change is required.

There are 55 numeric and 94 status/alarm fields. Fourteen ambiguous registers
remain excluded; see [register coverage](wpmg-register-coverage.md).
Package checks use isolated HA environments on macOS with simulated registers.
They do not establish Linux-container, HACS-UI or physical hardware compatibility.
