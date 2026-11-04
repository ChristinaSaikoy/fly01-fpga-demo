# Team workstation handoff — updated 2026-10-24

The [current task index](../docs/controller/2026-10-24/README.md) supersedes the
2026-10-21 task priority. Reviewed BY-06 source fixes are included: serialized
start/stop boundaries and the reusable targeted 1+20-step entry. Device-free
tests cover these fixes. The accepted demonstration used synthetic K230
observations replayed through the FPGA, not a live camera stream or motor loop.

Next work is FPGA-owned autonomous scheduling, peripherals and onboard power.
Those new RTL/interfaces are **not implemented by this synchronization**.
Current source still needs local device identity and a valid execution scope;
do not run old suite/history scripts as the next hardware command.

Start with [member_a's handoff](../docs/team/HANDOFF_BANGYI_HARDWARE_2026-10-21.md).
This directory closes the current EDGE/vision/communications source dependencies;
it is not a new hardware acceptance or a working K230 detector.

From any clone location, using Python 3.11 or newer:

```powershell
python -B team-runtime/verify.py
python -B team-runtime/hardware/HY04_O8_PRODUCTION_BUILD_2026-10-19/build.py
python -B team-runtime/hardware/HY04_O8_SIM_SUPPLEMENT_2026-10-19/run_sim.py
```

These commands only check files. After installing the Python dependencies in a
local virtual environment, run the device-free test suite:

```powershell
python -B -m venv .venv
.venv\Scripts\python.exe -m pip install -r team-runtime/requirements.txt
.venv\Scripts\python.exe -B team-runtime/verify.py --tests
```

`--tests` also requires `node` for JavaScript syntax checking. It uses simulated
ports/cameras and a loopback HTTP test server; it never runs a real device suite.
The dependency ranges are compatibility guidance, not a locked reproduction of a
teammate's interpreter. Existing environments can be reused after verification.

| Directory | Purpose |
|---|---|
| `desktop/` | Relocated WORK-13 host/UI, frozen calculation bundle, reviewed BY-06 start/stop fix and targeted 21-step source entry. Not an autonomous FPGA implementation. |
| `work12_reference/` | Byte-identical source inputs for the reference model and comparison; `DELIVERY.json` retains historical absolute evidence locations. Its old `verify_delivery.py` is not the portable verifier. |
| `formal_reference/` | Original 1+20 and complete formal plans/expected plus original acceptance function; no old device permission. |
| `hardware/HY04_O8_PRODUCTION_BUILD_2026-10-19/` | Production O8 RTL, IP/XDC, ROM inputs and local build entry. |
| `hardware/HY04_O8_SIM_SUPPLEMENT_2026-10-19/` | Seed0 300-step and ownership TB/vectors. |
| `hardware/artifacts/production_o8.bit` | Historical production image, SHA256 `93399a70892ece88300af96cd2dd27566b683f9eeecc41f394465182b5786eb4`; not a new build or an instruction to program. |
| `vision/FLY01_BY02_VISION/` | BY-02 complete vision source, configuration, tests and sample inputs; K230 input is still a protocol/file-replay draft. |
| `provenance/` | Original candidate identity before relocation. |

Frozen science and wire modules retain their exact bytes. The portable changes
only relocate the desktop bit/formal/reference paths, make external hashes
relative to this directory, and allow `FLY01_VIVADO_BIN` to select a local tool.
They produce a new candidate identity, **not** the previously board-tested host.
Historical development scripts are in `../development-history/tasks/`; some are
failed/obsolete diagnostics and still contain the author's paths. Do not execute
them by guessing that the highest task number is the active entry.

To open the demo after dependencies are ready:

```powershell
python -B team-runtime/desktop/app.py
```

It prints a local URL and stays idle. The default replay/software reference can
be started manually. This does not open a camera or program the FPGA by default.
K230 live acquisition and board tests need new local device bindings; old host
permissions and COM numbers have intentionally not been transferred.

The legacy `desktop/suite.py --execute` still runs the old full regression and
PC-camera suite. It is source to inspect, **not** the next K230 test command.
The reviewed targeted path is separate; it still requires current local device
bindings and an appropriate execution scope, not a copied historical approval.
`seal.py` records source hashes only; never treat it as hardware authorization.

Generated tool databases, raw scientific datasets, old live permissions,
personal remote-access setup and raw image/video captures are not included.
FULL source already lives under `src/full`; large external FULL datasets remain
documented external inputs, not a hidden requirement of this EDGE workstation.
