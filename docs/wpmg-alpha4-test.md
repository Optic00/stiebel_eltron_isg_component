# WPM G alpha 4 hardware test

For an ISG-connected WPM G only. This build never writes WPM G registers and
does not support the direct Genesis port. It requires Home Assistant 2026.11.0
or newer (the minimum in `hacs.json`).

## Install and roll back

1. Back up `/config/custom_components/stiebel_eltron_isg`.
2. Install the beta ZIP from the alpha 4 release, for example by replacing the
   directory's contents with `stiebel_eltron_isg.zip`.
3. Restart Home Assistant.
4. Keep your existing WPM G entry; its entities and settings carry over. For a
   new entry, select **WPM G (experimental, read-only)** in the setup form.
5. Enable any of the additional numeric and status entities you want to
   compare. The six original temperatures are enabled by default.

The old **Run WPM G diagnostics** button is gone. Its entry is removed from the
entity registry on the first start.

To roll back, restore the backed-up directory and restart Home Assistant. Keep
the backup until testing is complete. Alpha 3 was built for Home Assistant
2026.9 and pins an older Modbus library, so it may not load on 2026.11. If it
does not, disable the entry until a fixed build is available.

## What to report

- Do the values keep updating over several hours?
- Are they still fine after a normal Home Assistant restart? No heat-pump
  restart or setting change is needed.
- Do the condenser inlet and outlet temperatures and the active notifications
  match the controller display?
- Does the Home Assistant log contain a line from `pystiebeleltron` saying the
  controller does not serve a block (logged at info level, so enable info
  logging for `pystiebeleltron` before the restart), or a warning that it
  refused a block it answered before? Quote it. Entities of a block that is not
  served are unavailable.
- Download the integration diagnostics and inspect them for private
  information before sharing. They list the cached values, the optional blocks
  the library dropped, whether the last update succeeded and, if it failed, the
  exception class only. They make no Modbus request.

There are 55 numeric and 94 status or notification fields; see
[register coverage](wpmg-register-coverage.md).
