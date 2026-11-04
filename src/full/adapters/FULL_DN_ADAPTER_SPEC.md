# FULL_DN_ADAPTER_V1 Specification

Identity: ENGINEERING ADAPTER preserving the frozen demo.dnframe.v1 mapper-visible contract.

Binding:
- 32 Full runtime indices come from DN_32_INDEX_MAP.json.
- body IDs and slot order match FROZEN_32_DN_IDENTITY_AND_SLOT_ORDER, 32/32.

Window:
- FLY frame k corresponds to Full ticks [k*200, k*200+199], inclusive.

Aggregation:
- telemetry_count[slot] = number of spikes of that DN runtime index in the window.
- mapper-visible slot = 1 iff telemetry_count >= 1, else 0.
- multiple spikes never create values >1 in DNFrame.slots.
- spike count/rate is telemetry only and is not passed into the frozen mapper.

DNFrame fields:
- frame_id = k.
- timestamp_s = k * 0.02.
- dt_s = 0.02.
- source_timestep = k.
- schema_version = demo.dnframe.v1.
- slots = exactly 32 binary integers.

No MotorDrive or BodyRuntime execution occurs in FULL-3.
