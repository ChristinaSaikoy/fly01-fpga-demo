# S5-FPGA-1C MMIO Register Map - FROZEN

Protocol: `S5-FPGA-1C-MMIO-v1`. Bus: AXI4-Lite, 32-bit data, 12-bit byte address, little-endian. All registers are word aligned and require `WSTRB=0xF`.

Event encoding is fixed: `EVENT_DATA[8:0]` is neuron 0..470, bit 9 is 0 for stimulus or 1 for deterministic external noise, and bits 31:10 are zero. The only legal order is stimulus events in strictly ascending neuron index followed by noise events in strictly ascending neuron index. The wrapper passes accepted events through unchanged; it never reorders, deduplicates, or changes their meaning.

The deterministic runtime sequence is `IDLE -> RESET -> LOAD -> ARM -> RUN -> DONE -> READBACK -> LOAD`; code 15 is `ERROR`. Soft reset holds the frozen core in reset and then provides a 512-clock guard before LOAD. `ERROR_STATUS` and `ERROR` are latched until soft reset. Host transport occurs only in LOAD/READBACK and therefore cannot alter neural timestep semantics.

| Address | Register | Width | Access | Reset | Legal state / valid timing | Side effects and error behavior |
|---|---|---:|---|---|---|---|
| 0x000 | PROTOCOL_ID | 32 | R | 0xF1011C01 | all / anytime | Constant. Write is decode error 7. |
| 0x004 | CONTROL | 32 | W | 0 | bit0 all; bit1 READBACK | bit0 SOFT_RESET dominates; bit1 ACK_READBACK enters next LOAD. Unsupported command/state is error 1. |
| 0x008 | STATUS | 32 | R | 0 | all / anytime | `[3:0]` FSM, bit4 evt_ready, bit5 core_busy, bit6 done_latched, bit7 error, bit8 deadline violation. Write is error 7. |
| 0x00C | TIMESTEP_ID | 32 | R/W | 0 | LOAD, before events | First ID is 0, then +1. Illegal timing is error 1; commit detects sequence error 5. |
| 0x010 | EVENT_COUNT | 10 | R/W | 0 | LOAD, before events | Expected count 0..942. Range/timing failure is error 4. |
| 0x014 | EVENT_DATA | 10 | W | 0 | LOAD, before commit | AXI write completes only after one frozen-core event handshake, then accepted count increments. Encoding/index error 2; order/duplicate error 3; excess/timing error 4. |
| 0x018 | EVENT_COMMIT | 1 | W | 0 | LOAD, count exact, core idle | bit0 enters ARM; ARM generates the sole step pulse. State/command error 1, count error 4, ID error 5, busy error 6. |
| 0x01C | EVENT_ACCEPTED_COUNT | 10 | R | 0 | all / anytime | Exact accepted events for current timestep. Write is error 7. |
| 0x020 | COMPLETED_TIMESTEP_ID | 32 | R | 0xFFFFFFFF | valid after DONE latch | Snapshot ID. Write is error 7. |
| 0x024 | STATE_INDEX | 9 | R/W | 0 | READBACK for write | Select 0..470. Bad state/index is error 1. |
| 0x028 | STATE_DATA | 18 | R | 0 | READBACK | Sign-extended raw signed S18/F13 two's-complement state. Read outside READBACK is error 1. |
| 0x02C | DN_COUNTER_INDEX | 5 | R/W | 0 | READBACK for write | Select frozen `dn_local` slot 0..31. Bad state/index is error 1. |
| 0x030 | DN_COUNTER_DATA | 32 | R | 0 | READBACK | Exact cumulative counter. Read outside READBACK is error 1. |
| 0x034 | ACC_SAT_COUNTER | 32 | R | 0 | READBACK | Exact cumulative count. Read outside READBACK is error 1. |
| 0x038 | STATE_SAT_COUNTER | 32 | R | 0 | READBACK | Exact cumulative count. Read outside READBACK is error 1. |
| 0x03C | FIFO_OVERFLOW | 32 | R | 0 | READBACK | Frozen top plus core overflow count. Read outside READBACK is error 1. |
| 0x040 | EVENT_DROP | 32 | R | 0 | READBACK | Frozen top plus core drop count. Read outside READBACK is error 1. |
| 0x044 | TIMESTEP_CYCLES | 32 | R | 0 | READBACK | Core execution cycles only. Read outside READBACK is error 1. |
| 0x048 | ERROR_STATUS | 32 | R | 0 | all / anytime | First error wins and only soft reset clears it. Write is error 7. |
| 0x04C | STEP_CONFIG | 1 | R/W | 0 | LOAD, before events | bit0 is `DN_COUNT_ENABLE` and is passed unchanged for the committed step. Bad timing/reserved bits is error 1. |
| 0x050 | SOFT_RESET | 1 | W | 0 | all / anytime | bit0=1 resets only protocol and frozen core, retains JTAG transport, and starts the guard. Zero/reserved bits is error 1. |

All illegal writes return AXI `SLVERR`; illegal reads return `SLVERR`. Both latch `ERROR_STATUS` and enter ERROR. Status, protocol ID, error status, configured timestep/count, accepted count, completed ID, indices, and step configuration remain readable for diagnostics in ERROR.

Per timestep, the host writes `TIMESTEP_ID`, `EVENT_COUNT`, and `STEP_CONFIG.DN_COUNT_ENABLE`; writes all canonical `EVENT_DATA`; commits; polls `STATUS.done_latched`; then reads all 471 states, all 32 DN counters, both saturation counters, overflow/drop, cycles, and completed ID. `ACK_READBACK` is required before the next timestep.
