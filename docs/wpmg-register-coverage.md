# WPM G primary FC04 coverage

Source: [ISG Modbus manual, chapter 9, printed pages 40–45](https://www.stiebel-eltron.com.au/download/1685919441_321798-44755-9770_ISG%20Modbus_en.pdf).
The September diagnostic returned all 163 documented primary addresses.
149 fields are decoded according to the manual. This confirms the read path on
one installation, not every sensor value or status transition on every device.
Temperature differences in K have no absolute-temperature device class.
Boolean fields accept only 0 or 1; other codes and 0x8000 are unavailable.
New entities are disabled by default to keep the initial UI manageable;
all declared fields remain in the polling plan. Rejected individual addresses
are unavailable and retried after five minutes; valid neighbours continue to
update. Connection, busy, protocol and timeout errors fail the whole poll.

## Fault isolation and debugging

Normal polling splits a block only after Modbus exception code 2. A rejected
single address becomes unavailable immediately, including after earlier valid
reads. It is retried after five minutes; successful retries restore the value.
Learned block subdivisions also support devices that reject long reads. Parent blocks are re-probed after five minutes and recovered subdivisions
are removed. Learned splits are also cleared after a manual diagnostic scan
and when the entry reloads.

Each poll permits at most 149 normal single-word reads plus 32 exploratory
requests and has a 20-second deadline. Healthy devices use eleven block reads.
When exploration runs out, untested words are marked `not_probed_budget` and
only those values are unavailable. Later polls continue narrowing the failed
blocks. A request timeout or the overall deadline fails the entire poll.

Download Home Assistant diagnostics for `wpmg_polling`: FC04 references, field
names, raw words, current availability reasons, failed request details,
timestamps, poll duration, rejection counts and learned block subdivisions. The report keeps
one row per declared address, not an unbounded event log. It distinguishes a
real device sentinel, an invalid decoded value, a rejected address, pending
retry and an exhausted exploration budget. Exception messages and connection
identifiers are not copied into this report.

The diagnostic button still scans all 163 documented addresses independently,
including the excluded fields, and produces `wpmg_diagnostic`. Normal polling
and the manual scan share a lock so they do not compete for the device.
The normal polling deadline starts after the scan releases that lock. After a completed
scan, normal polling can re-probe temporarily skipped addresses immediately on
its next cycle. Setup remains possible if the device responds but all fields
are unavailable; this is not automatic model detection.

## Excluded fields

14 registers remain diagnostic-only:

| References | Reason |
| --- | --- |
| 36000 | Printed room-temperature factor gives an implausible value. |
| 36035–36036, 36050–36055 | Counter word ordering is not established; runtime samples conflict with the printed LSW/MSW order. The manual's 32-bit example also uses 65535 instead of 65536. |
| 36121 | The meaning of this separate energy total and its relation to the other meter is not established. |
| 36122 | Documented as boolean but the capture contains another code. |
| 36123 | Decoded dew-point value is implausible; no substitute scaling is assumed. |
| 37701–37702 | Stages/speed are labelled boolean; the stage sample is not boolean. |

No writes, holding-register polling, secondary units or direct Genesis support.
Existing six entity keys remain unchanged. The condenser display-label
correspondence still needs confirmation; the API retains the manual's names.

| Reference | Field | Unit | Exposed |
| --- | --- | --- | --- |
| 36000 | `room_temperature` | °C | no |
| 36001 | `buffer_cylinder_temperature` | °C | yes |
| 36002 | `heating_circuit_1_flow_temperature` | °C | yes |
| 36003 | `heating_circuit_2_flow_temperature` | °C | yes |
| 36004 | `heating_circuit_3_flow_temperature` | °C | yes |
| 36005 | `heating_circuit_4_flow_temperature` | °C | yes |
| 36006 | `heating_circuit_5_flow_temperature` | °C | yes |
| 36007 | `heating_circuit_2_return_temperature` | °C | yes |
| 36008 | `heating_circuit_3_return_temperature` | °C | yes |
| 36009 | `heating_circuit_4_return_temperature` | °C | yes |
| 36010 | `heating_circuit_5_return_temperature` | °C | yes |
| 36011 | `cooling_circuit_return_temperature` | °C | yes |
| 36012 | `cooling_cylinder_temperature` | °C | yes |
| 36013 | `cooling_cylinder_return_temperature` | °C | yes |
| 36014 | `cooling_cylinder_flow_temperature` | °C | yes |
| 36015 | `dhw_draw_off_control_flow_temperature` | °C | yes |
| 36016 | `dhw_draw_off_control_return_temperature` | °C | yes |
| 36017 | `dhw_charging_system_return_temperature` | °C | yes |
| 36018 | `dhw_draw_off_control_cylinder_temperature` | °C | yes |
| 36019 | `system_sensor_upper_dhw_temperature` | °C | yes |
| 36020 | `system_sensor_lower_dhw_temperature` | °C | yes |
| 36021 | `brine_inlet_temperature` | °C | yes |
| 36022 | `brine_outlet_temperature` | °C | yes |
| 36023 | `hot_gas_temperature` | °C | yes |
| 36024 | `condenser_inlet_temperature` | °C | yes |
| 36025 | `condenser_outlet_temperature` | °C | yes |
| 36026 | `liquid_line_temperature` | °C | yes |
| 36027 | `suction_gas_temperature` | °C | yes |
| 36028 | `pool_flow_temperature` | °C | yes |
| 36029 | `pool_return_temperature` | °C | yes |
| 36030 | `hot_gas_mode_dhw_flow_temperature` | °C | yes |
| 36031 | `sg_ready_input_1` | boolean | yes |
| 36032 | `sg_ready_input_2` | boolean | yes |
| 36033 | `external_stop_pool_heating` | boolean | yes |
| 36034 | `external_start_brine_pump` | boolean | yes |
| 36035 | `electrical_energy_kwh_total_lsw` | kWh | no |
| 36036 | `electrical_energy_kwh_total_msw` | kWh | no |
| 36050 | `hours_run_compressor_lsw` | h | no |
| 36051 | `hours_run_compressor_msw` | h | no |
| 36052 | `hours_run_booster_heater_lsw` | h | no |
| 36053 | `hours_run_booster_heater_msw` | h | no |
| 36054 | `hours_run_dhw_heating_lsw` | h | no |
| 36055 | `hours_run_dhw_heating_msw` | h | no |
| 36100 | `outside_temperature_averaged` | °C | yes |
| 36101 | `dhw_temperature_weighted` | °C | yes |
| 36102 | `evaporation_temperature_in_high_pressure_range` | °C | yes |
| 36103 | `condensation_temperature_in_high_pressure_range` | °C | yes |
| 36104 | `condensation_temperature_in_low_pressure_range` | °C | yes |
| 36105 | `superheating` | K | yes |
| 36106 | `supercooling` | K | yes |
| 36107 | `pressure_low_pressure_side` | bar | yes |
| 36108 | `pressure_high_pressure_side` | bar | yes |
| 36109 | `l1_current` | A | yes |
| 36110 | `l2_current` | A | yes |
| 36111 | `l3_current` | A | yes |
| 36112 | `l1_n_voltage` | V | yes |
| 36113 | `l2_n_voltage` | V | yes |
| 36114 | `l3_n_voltage` | V | yes |
| 36115 | `l1_l2_voltage` | V | yes |
| 36116 | `l2_l3_voltage` | V | yes |
| 36117 | `l3_l1_voltage` | V | yes |
| 36118 | `l1_power_consumption` | W | yes |
| 36119 | `l2_power_consumption` | W | yes |
| 36120 | `l3_power_consumption` | W | yes |
| 36121 | `energy_total` | kWh | no |
| 36122 | `comfort_mode` | boolean | no |
| 36123 | `room_dew_point_temperature` | °C | no |
| 36124 | `set_buffer_cylinder_temperature` | °C | yes |
| 36125 | `start_delay_active` | boolean | yes |
| 36126 | `current_output_stage_compressor` | stage | yes |
| 36127 | `current_output_stage_internal_booster_heater` | stage | yes |
| 36128 | `percentage_compressor_speed` | % | yes |
| 37500 | `control_signal_external_booster_heater` | boolean | yes |
| 37501 | `control_signal_internal_booster_heater_stage_2` | boolean | yes |
| 37502 | `control_signal_heating_circuit_1_circulation_pump` | boolean | yes |
| 37503 | `control_signal_condenser` | boolean | yes |
| 37504 | `control_signal_internal_booster_heater_stage_1` | boolean | yes |
| 37505 | `control_signal_hot_gas_circulation_pump` | boolean | yes |
| 37506 | `control_signal_brine_pump` | boolean | yes |
| 37507 | `control_signal_external_booster_heater_dhw_circulation_pump` | boolean | yes |
| 37508 | `control_signal_external_relay_for_brine_pump` | boolean | yes |
| 37600 | `feedback_external_booster_heater` | boolean | yes |
| 37601 | `feedback_internal_booster_heater` | boolean | yes |
| 37602 | `control_signal_hot_gas_control` | boolean | yes |
| 37603 | `heat_pump_off` | boolean | yes |
| 37604 | `heat_pump_ready_to_start` | boolean | yes |
| 37650 | `control_signal_dhw_draw_off_control_flow_dhw_circulation_pump` | boolean | yes |
| 37651 | `control_signal_dhw_charging_system_control` | boolean | yes |
| 37652 | `control_signal_dhw_charging_system_dhw_circulation_pump` | boolean | yes |
| 37653 | `control_signal_dhw_draw_off_control_cylinder_heating` | boolean | yes |
| 37655 | `control_signal_cooling_circuit_dhw_circulation_pump` | boolean | yes |
| 37656 | `control_signal_pool_dhw_circulation_pump` | boolean | yes |
| 37657 | `control_signal_cooling_circuit_control` | boolean | yes |
| 37660 | `control_signal_pool_control` | boolean | yes |
| 37661 | `note_if_mixing_valve_used_for_passive_cooling` | boolean | yes |
| 37663 | `control_signal_compressor` | boolean | yes |
| 37700 | `compressor_cannot_start` | boolean | yes |
| 37701 | `compressor_available_output_stages` | boolean | no |
| 37702 | `compressor_speed` | boolean | no |
| 39000 | `level_1_notification` | boolean | yes |
| 39001 | `level_2_notification` | boolean | yes |
| 39002 | `level_3_notification` | boolean | yes |
| 39003 | `level_1_notification_high_pressure` | boolean | yes |
| 39004 | `level_1_notification_low_pressure` | boolean | yes |
| 39005 | `level_1_notification_hot_gas_temperature` | boolean | yes |
| 39006 | `level_1_notification_operating_pressure` | boolean | yes |
| 39007 | `level_1_notification_hot_gas_line_sensor` | boolean | yes |
| 39008 | `level_1_notification_liquid_line_sensor` | boolean | yes |
| 39009 | `level_1_notification_suction_gas_sensor` | boolean | yes |
| 39010 | `level_1_notification_flow_rate_pressure_brine_or_condenser` | boolean | yes |
| 39011 | `level_1_notification_bm_card_phase_sequence` | boolean | yes |
| 39012 | `level_1_notification_inverter_fault` | boolean | yes |
| 39013 | `level_3_notification_low_source_temperature` | boolean | yes |
| 39014 | `level_1_notification_low_compressor_speed` | boolean | yes |
| 39015 | `level_1_notification_low_superheating` | boolean | yes |
| 39016 | `level_1_notification_outside_pressure_ratio` | boolean | yes |
| 39017 | `level_1_notification_outside_operating_range` | boolean | yes |
| 39018 | `level_1_notification_brine_temperature_outside_range` | boolean | yes |
| 39019 | `level_2_notification_brine_inlet_sensor` | boolean | yes |
| 39020 | `level_2_notification_brine_outlet_sensor` | boolean | yes |
| 39021 | `level_2_notification_condenser_inlet_sensor` | boolean | yes |
| 39022 | `level_2_notification_condenser_outlet_sensor` | boolean | yes |
| 39023 | `level_2_notification_outside_temperature_sensor` | boolean | yes |
| 39024 | `level_2_notification_system_flow_sensor` | boolean | yes |
| 39025 | `level_2_notification_heating_circuit_1_sensor` | boolean | yes |
| 39026 | `level_2_notification_heating_circuit_2_sensor` | boolean | yes |
| 39027 | `level_2_notification_heating_circuit_3_sensor` | boolean | yes |
| 39028 | `level_2_notification_heating_circuit_4_sensor` | boolean | yes |
| 39029 | `level_2_notification_heating_circuit_5_sensor` | boolean | yes |
| 39030 | `level_2_notification_dhw_charging_circuit_sensor` | boolean | yes |
| 39031 | `level_2_notification_dhw_sensor` | boolean | yes |
| 39032 | `level_2_notification_cooling_buffer_sensor` | boolean | yes |
| 39033 | `level_2_notification_cooling_cylinder_flow_sensor` | boolean | yes |
| 39034 | `level_2_notification_cooling_circuit_return_sensor` | boolean | yes |
| 39035 | `level_2_notification_source_circuit_spread_max` | boolean | yes |
| 39036 | `level_2_notification_dhw_centre_sensor` | boolean | yes |
| 39037 | `level_2_notification_dhw_return_sensor` | boolean | yes |
| 39038 | `level_2_notification_dhw_hot_gas_sensor` | boolean | yes |
| 39039 | `level_2_notification_internal_booster_heater` | boolean | yes |
| 39040 | `level_3_notification_condenser_maximum_temperature` | boolean | yes |
| 39041 | `level_2_notification_max_brine_inlet` | boolean | yes |
| 39042 | `level_2_notification_min_brine_inlet` | boolean | yes |
| 39043 | `level_2_notification_min_brine_outlet` | boolean | yes |
| 39044 | `level_3_notification_min_dhw_circulation_return` | boolean | yes |
| 39045 | `level_3_notification_min_dhw_circulation_temperature` | boolean | yes |
| 39046 | `level_3_notification_heating_circuit_1_temperature` | boolean | yes |
| 39047 | `level_3_notification_heating_circuit_2_temperature` | boolean | yes |
| 39048 | `level_3_notification_heating_circuit_3_temperature` | boolean | yes |
| 39049 | `level_3_notification_heating_circuit_4_temperature` | boolean | yes |
| 39050 | `level_3_notification_heating_circuit_5_temperature` | boolean | yes |
| 39051 | `level_3_notification_dhw_circulation_return_temperature` | boolean | yes |
| 39052 | `notification_central_message` | boolean | yes |
| 39053 | `level_3_notification_cooling_circuit_temperature` | boolean | yes |
| 39054 | `level_3_notification_cooling_buffer_temperature` | boolean | yes |
| 39055 | `level_2_notification_humidity_sensor` | boolean | yes |
| 39056 | `level_2_notification_cooling_buffer_return_sensor` | boolean | yes |
| 39057 | `level_3_notification_room_temperature_sensor` | boolean | yes |
| 39058 | `level_1_notification_inverter_communication` | boolean | yes |
| 39059 | `level_2_notification_pool_return_sensor` | boolean | yes |
| 39060 | `level_2_notification_cooling_heating_circuit_1_sensor` | boolean | yes |
| 39061 | `level_2_notification_dhw_cylinder_sensor` | boolean | yes |
| 39062 | `level_2_notification_maximum_pasteurisation_time` | boolean | yes |
| 39063 | `level_3_notification_external_alarm` | boolean | yes |
