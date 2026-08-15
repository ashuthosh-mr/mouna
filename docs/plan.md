# PARISCV v2: Minimal OpenHW/CV-X-IF Custom-Instruction Discovery Pipeline

## Context
This supersedes the earlier Euro-RV-deadline-driven plan (that plan is dropped — no deadline now, and the target core changed).

Goal: build an open-source tool, aimed at RISC-V community visibility (and portfolio/hiring signal, given you're currently between jobs), that discovers profitable custom instructions for an OpenHW CORE-V processor (CV32E40X/CV32E40P) and validates them, with a **fast Spike+microarchitecture-model inner loop** pruning candidates before an expensive **Verilator RTL** confirmation step. This directly reuses ideas and code from your existing `/home/kitta/pariscv` (VexRiscv+GDB trace infra) and `/home/kitta/paragato/profiler` (Spike-based Embench harness), retargeted at OpenHW cores via the **CV-X-IF** interface instead of a bespoke VexRiscv plugin.

Novelty check performed (web search, see prior turn): closest prior art is **CIDRE** (arXiv 2509.15782, Sept 2025 — hotspot analysis → custom instruction suggestion → nML model, Embench/MiBench, up to 2.47x speedup), plus OpenASIP, ARISE, Longnail/CoreDSL, GenIE, MARVEL. None of these ship as a maintained, installable open-source tool targeting a real, community-adopted core via its standard extension interface (CV-X-IF) — that gap is the differentiator to lean on, not "nobody has automated ISE discovery before."

Design decision already made with you: **start with fine-grained instruction fusion** (combining short sequences of existing ops) as the custom-instruction search space — not arbitrary new functional-unit synthesis — since CV-X-IF gives a fixed, documented integration contract that keeps the "core generator" step bounded. Coarser-grained/domain-specific functional units are explicit future work (also useful later for performance projection of "next-gen domain-optimized" cores).

## Current machine state (verified)
- `verilator` is installed (`/usr/local/bin/verilator`, plus copies under `~/tools` and `~/Calligo`).
- A RISC-V GCC toolchain exists at `/home/kitta/revolution/bin/riscv32-unknown-elf-gcc` (**PULP-flavored GCC 7.1.1 from 2017**, multilibs are `rv32imfcxpulpv2`, `rv32imcxgap8`, etc — this is the wrong toolchain for OpenHW/CV-X-IF work and should not be reused; too old, wrong custom-extension ABI baked in).
- Spike source exists at `/home/kitta/sifive/riscv-isa-sim` (**mainline `riscv-software-src/riscv-isa-sim`**, no CV-X-IF/xcorev support built in — expected, since CV-X-IF instructions are core-specific extensions, not something upstream Spike knows about).
- No OpenHW CV32E repo present anywhere on the machine yet — needs cloning.
- Reusable prior work:
  - `/home/kitta/pariscv/pariscv/flow.py` — `gcc_flow()`/`vex_flow()` pattern for compile→sim orchestration (reusable structure, not the VexRiscv-specific bits).
  - `/home/kitta/pariscv/pariscv/flow.py:log_capture()` — existing instruction-frequency-from-trace logic; conceptually reusable for the hotspot-finding stage even though it was built for a GDB/VexRiscv trace, not Spike.
  - `/home/kitta/paragato/profiler/pariscv.sh`, `main.c`/`beebsc.c` — working Embench-kernel compile+Spike-trace harness; reusable as the trace-generation half almost as-is.
  - `/home/kitta/pariscv/pariscv/gdb-alt/IMpariscv` — C++ GDB-stub/FST-trace tool; likely not needed once Verilator+CV-X-IF testbench trace dumps replace GDB-based tracing, but worth a quick look before discarding.

## Recommended minimal pipeline (v1 scope)

```
Embench/benchmark C source
        │
        ▼
riscv-gnu-toolchain (fresh build, targeting rv32i[m][c] + reserved custom opcode space)
        │
        ▼
Spike ISS run, instruction trace (-l / commit log)
        │
        ▼
Python: trace parser  →  hotspot / fusable-sequence finder (candidate instructions)
        │
        ▼
Python: microarchitectural model (CV32E40X/40P pipeline: stage count, hazards,
        forwarding, branch penalty, documented CV-X-IF issue/writeback timing)
        →  fast estimated speedup per candidate, rank & prune
        │
        ▼
Top-N candidates → hand/templated CV-X-IF coprocessor RTL (fixed-function fused-op unit)
        │
        ▼
Verilator RTL sim (OpenHW cv32e40x + CV-X-IF coprocessor) → real cycle count
        │
        ▼
Compare real vs. estimated → report speedup, model error, keep/discard candidate
```

Key minimal-setup pieces to stand up, in order:
1. **Toolchain**: build a fresh `riscv-gnu-toolchain` (upstream, not the 2017 PULP fork) targeting `rv32imc` (or whatever base ISA CV32E40X uses), confirm it can assemble inline-asm custom opcodes for candidate instructions (standard approach: `.insn` directives — no toolchain patching needed for v1).
2. **OpenHW core**: clone `cv32e40x` (has documented CV-X-IF support) — check if `core-v-verif` is needed or if the core repo's own testbench/Makefiles are enough for a minimal Verilator build. Confirm CV-X-IF example coprocessor already in the repo (OpenHW ships a reference "example" extension unit) — reuse that as the template for candidate fused-op units instead of writing CV-X-IF glue from scratch.
3. **Spike**: mainline Spike is fine for the ISS trace step for the *base* ISA hotspot-finding; candidate custom instructions don't need to execute in Spike for v1 — the microarch model works directly off which existing-instruction sequences in the trace are fusable, so Spike itself never needs new opcodes registered. (Skip building a Spike custom-extension plugin entirely for v1 — real risk/complexity is not worth it for the fast-filter stage.)
4. **Python trace analyzer + microarch model**: one script parses Spike's commit log into a sequence, a second module implements the CV32E40X timing model (documented in the OpenHW user manual) and scores candidate fusions.
5. **Verilator validation harness**: compile candidate benchmark variant with inline-asm custom instruction, run against cv32e40x+CV-X-IF coprocessor in Verilator, compare cycle count to the model's prediction.

## What's explicitly out of scope for v1 (future work)
- Arbitrary new functional-unit synthesis (HLS-like generation) — only fixed-function fused-op units templated off OpenHW's example CV-X-IF coprocessor.
- Multi-core abstraction (CV32E40P vs 40X vs others) — pick one (recommend CV32E40X, since it's the CV-X-IF reference target) and get it fully working before generalizing.
- Automatic RTL *generation* of the coprocessor — v1 can hand-write/template a small parameterizable fused-ALU-op unit; full auto-codegen is a v2 goal once the discovery+scoring half is proven.
- Performance projection for hypothetical "next-gen domain-optimized" cores — natural extension once the microarch model is validated against real CV32E40X numbers, but not part of getting v1 working.

## Decisions locked in during implementation (2026-08-15)
- **Target core: CV32E40X**, confirmed. CV32E40P was considered for its Xpulp+F support, but verified directly in source (grep across `.md`/`.sv`/`.rst`) that CV32E40P has **no CV-X-IF at all** — only the older, pipeline-coupled APU interface. Porting Xpulp/F into CV32E40X would require re-merging core-internal RTL (FPU in execute stage, extended regfile/forwarding, hardware-loop fetch/decode logic) and would partially undo CV-X-IF's decoupling — out of scope for this project. `cores/cv32e40p` is kept cloned in the repo as a reference only, not part of the active pipeline.
- **No hardware float / no Xpulp in v1.** Base ISA target is `rv32imc_zicsr_zifencei` (matches CV32E40X's actual supported extensions: `RV32[I|E]`, `[A]`, `[M|Zmmul]`, `Zca_Zcb_Zcmp_Zcmt`, `[Zba_Zbb_Zbs|...Zbc...]`, `Zicntr/Zihpm/Zicsr/Zifencei`, `[Xif]`). Xpulp/F-style acceleration becomes something *our tool discovers and adds itself* via CV-X-IF later, rather than something inherited from the core — a better story for the project anyway. FP-heavy Embench kernels may need soft-float or deprioritizing; revisit at benchmark-selection time.
- **Toolchain solved, no from-scratch build needed**: `/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3` is a modern, unpatched GCC 14.2.0 (xPack build) with native `rv32imc/ilp32` multilib support — verified by compiling/linking a real RV32IMC ELF. This replaces the plan's original "build fresh upstream riscv-gnu-toolchain" step entirely.
- Leaving `/home/kitta/pariscv/pariscv/gdb-alt/IMpariscv` (GDB-stub/FST tool) unused for now — Verilator's own trace dump covers what's needed.

## Progress so far
- `/home/kitta/paragato/` scaffolded as a git repo: `cores/` (`cv32e40x`, `core-v-verif`, `cv32e40p` for reference), `bench/embench-iot` (full upstream suite copied from `~/apps/embench-iot`), `tools/`, `rtl/`, `docs/`.
- Confirmed `cv32e40x/rtl/cv32e40x_if_xif.sv` exists — CV-X-IF RTL is present and real in the cloned core.
- `ext1.py`/`ext.py` source (the original PyInstaller-frozen analysis tool) was searched for across `~/apps` and confirmed **not recoverable** — only the compiled binary and PyInstaller build artifacts exist, no `.py` source. Not reusable; new trace-analyzer/model code will be written from scratch (as already scoped).

## Bring-up log (2026-08-15) — what works, what bit us

### Spike ISS: WORKING ✅
- Binary already built at `/home/kitta/sifive/riscv-isa-sim/build/spike` (mainline, v1.1.1-dev).
- Must pair with the **rv32** proxy kernel at `/home/kitta/sifive/riscv64/riscv32-unknown-elf/bin/pk` (the one at `/home/kitta/sifive/riscv-pk/build/pk` is an **ELF64** build and fails with "cannot execute 64-bit program on RV32 hart").
- The `sifive/riscv64` GCC 10.1.0 (`riscv64-unknown-elf-gcc`) is what matches that pk. Note its binutils is too old for `_zicsr`/`_zifencei` in `-march` — use plain `-march=rv32imac -mabi=ilp32` for Spike-side builds.
- Verified working command (prints program output, and `-l` yields a full instruction commit-log trace):
  ```
  spike -l --isa=rv32imac <rv32-pk> <prog.elf>
  ```
- Smoke test lives at `/home/kitta/paragato/tools/spike_smoke/` (hello.c, hello_rv32.elf, spike_trace.log ≈283k trace lines).

### CV32E40X + Verilator: builds and runs, program-completion still unconfirmed ⚠️
Build works; the RTL elaborates with CV-X-IF (`if_xif` objects present in the Verilator build). Required workarounds, all via make variables (no core RTL edits):
- `CV_SW_TOOLCHAIN=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3`, `CV_SW_PREFIX=riscv-none-elf-`, `CV_SW_MARCH=rv32imc_zicsr_zifencei` (newer binutils **requires** explicit `_zicsr` or `crt0.S` fails on `csrw`).
- `SV_CMP_FLAGS="-Wno-COMBDLY"` — Verilator 5.036 is newer than the Makefile expects and promotes a benign `cv32e40x_sim_clock_gate.sv` warning to a fatal error.
- `VERI_CFLAGS="-std=gnu++17 -O2"` — Verilator 5.036 needs C++14+; Makefile hardcodes `gnu++11`. **Careful:** overriding this on the command line also clobbers the Makefile's `-DVCD_TRACE`, so `WAVES=1` silently produces no VCD unless you append `-DVCD_TRACE` yourself.
- `VERI_CUSTOM=../../tests/programs/custom`, `SIM_TEST_PROGRAM_RESULTS=$PWD/results/test_program`, `SIM_BSP_RESULTS=$PWD/results/bsp` — these are referenced by the lightweight `core` sim flow but only *defined* in the `uvmt` (UVM) makefiles.

### Real bugs found
1. **Print/exit address mismatch (patched).** `bsp/syscalls.c` routes `_write`/`_exit` to `corev_uvmt.h` virtual-peripheral addresses (`CV_VP_VIRTUAL_PRINTER_BASE = 0x00800000`, exit = `CV_VP_STATUS_FLAGS_BASE+4 = 0x008000c4`), but the `core` testbench's `tb/core/mm_ram.sv` decoded `MMADDR_PRINT = 0x10000000` / `MMADDR_EXIT = 0x20000004`. stdout writes were silently discarded. **Patched `mm_ram.sv`** to the BSP's addresses (comment added in-file). That BSP was written for the `uvmt` env, not the `core` env.
2. **Startup cost dominates everything.** `bsp/crt0.S` does `memset(_edata .. _end)`, and `bsp/link.ld` grows `.heap` to the end of a 4MB RAM (`ram LENGTH = 0x400000`), so `.heap` ≈ `0x3fcc50` ≈ **4MB zeroed before `main()` runs**. Cycle caps of 20k/50k/200k/60M were all killing the sim *during startup memset* — this, not a hang, explains the "it never prints" symptom. Verilator does ~60M cycles in ~76s here.
3. `tb_top_verilator.cpp` calls `dump_memory()` **before** the sim loop, writing 1,048,576 bytes one-per-line with a flush each — this is why some runs appeared to hang for 10+ minutes at startup. Not a correctness bug, just slow I/O.

### Diagnostic asset created
`cores/core-v-verif/cv32e40x/tests/programs/custom/pg_minimal/` — a bare-metal test (no newlib, no printf, no CSR checks) that writes a marker string straight to the print peripheral then writes the exit register. Use it to separate "core executes + peripherals decode" from "newlib/printf works".

### RESOLVED — root cause found and fixed (2026-08-15)
The real bug: `cv32e40x_tb_wrapper.sv`'s instantiation of `cv32e40x_core` never connected **`data_wdata_o`/`data_rdata_i`** at all — every store wrote 0x0, every load returned 0x0. Verilator's PINMISSING warning for this was silently suppressed by the Makefile's `--Wno-lint`. This explains every earlier symptom (no print output, "hangs" that were really newlib's stdio init looping on corrupted pointers, `memset` appearing to "succeed" only because zeroing already matched the corrupted-to-zero data). Not X-state, not nondeterminism, not the address remap (which was itself a real, separate, correctly-diagnosed bug) — all of that was true but secondary to this.

**Fixed in `cv32e40x_tb_wrapper.sv`**: added `.data_wdata_o(data_wdata)` / `.data_rdata_i(data_rdata)` to the core instantiation (comment left in-file). Also added an optional `+pctrace` debug hook (dumps ID-stage PC every cycle) since this testbench has no RVFI tracer available (it instantiates `cv32e40x_core` directly, not `cv32e40x_wrapper`, so `cv32e40x_core_log`'s illegal-instruction logging isn't wired in either).

**Verified working**: `hello-world` now prints the full banner and CSR dump correctly and exits cleanly at cycle **179040**. A hand-written `pg_matmult` kernel (8x8 int matmul, `rdcycle`-timed) gives:
- Spike ISS: checksum=7, "cycles"=4085 (really just instruction count, Spike has no microarchitecture)
- CV32E40X RTL (Verilator): checksum=7 (correct, matches), **cycles=6356**

This Spike-vs-RTL gap (~1.56x) is the first real evidence for why the project needs an actual microarch model rather than treating Spike's count as a proxy.

**Measurement purity verified**: confirmed via disassembly (on both the sifive toolchain used for Spike and the xpack toolchain used for Verilator) that the `rdcycle`-timed window contains only the `matmult()` triple-nested loop — `init()` runs before the first `rdcycle`, and the checksum + `printf` run strictly after the second, with no calls in between. Hardened `rdcycle()` in `pg_matmult.c` with a `"memory"` clobber so this holds under any optimization level/compiler, not just incidentally. Reran both sides after the change — numbers unchanged (4085 / 6356), as expected.

**core-v-verif also ships an official Embench integration** (`cv32e40x/tests/embench/`, `make embench SIMULATOR=...` from `sim/uvmt`) — but it only supports UVM-capable commercial simulators (Questa/VCS/Xcelium/dsim), confirmed via zero references to `verilator` anywhere in the `uvmt` build files. Not usable with our toolchain. Its `chipsupport.c` (cycle-counting via a `TICKS_ADDR` testbench peripheral) was useful as reference; we used direct `rdcycle`/mcycle instead, which is more authoritative since it's the core's own counter.

**Diagnostic assets on disk** (reusable for every future kernel):
- `cv32e40x/tests/programs/custom/pg_minimal/` — bare-metal marker-string test, no newlib
- `cv32e40x/tests/programs/custom/pg_matmult/` — 8x8 matmul with rdcycle timing (first real kernel)
- `/home/kitta/paragato/tools/bare/` — raw assembly tests (bare.S, bare2.S) used to isolate the wdata/rdata bug
- `/home/kitta/paragato/tools/spike_smoke/` — Spike-side smoke tests and traces

### Still open / near-term cleanup
- The full manual `make veri-test TEST=... SV_CMP_FLAGS=... VERI_CFLAGS=... VERI_CUSTOM=... SIM_TEST_PROGRAM_RESULTS=... SIM_BSP_RESULTS=...` invocation is long and easy to get wrong — should be wrapped into a single repeatable script (e.g. `tools/run_cv32e40x.sh <test-name>`) before adding more kernels.
- `hello-world`'s 179040-cycle run is dominated by newlib/CSR-check startup, not the interesting kernel — per-region `rdcycle` (as `pg_matmult` already does) is the right pattern going forward, not whole-program cycle counts.
- Not yet committed to git — the `mm_ram.sv` and `cv32e40x_tb_wrapper.sv` fixes only exist in the working tree.

## Euro-RV 2026 (2026-08-15)
Checked https://euro-rv.github.io/: submission deadline **2026-08-20** (5 days out from today), workshop **2026-10-31**. Explicitly accepts Work-in-Progress/poster submissions ("early research ideas... parts of ongoing work intended for a future conference submission"), up to 2 pages (soft limit) + references, LaTeX main-conference template, EasyChair, single-blind. Given the timeline, a 2-page WIP describing the architecture + the CV32E40X testbench bug found/fixed (a legitimate standalone contribution) + the Spike-vs-RTL divergence result above is realistic; a full paper is not.

## Next step
Bring up the base toolchain → CV32E40X core → Verilator loop with zero custom instructions first (compile a trivial/Embench program with the xPack toolchain, run it through `core-v-verif`'s CV32E40X Verilator testbench, confirm it executes and produces a cycle count) — before touching Spike tracing or the microarch model. This proves the RTL-validation half of the pipeline works before building the discovery half on top of it.

## Verification
- End-to-end smoke test: one Embench kernel (start with `matmult-int`, already working in `/home/kitta/paragato/profiler`) run through the full chain — Spike trace → candidate found → model estimate → Verilator RTL confirmation — with the model's cycle estimate and Verilator's actual cycle count both printed, so the very first run already produces the paper's/tool's core evidence (estimated vs. real speedup).
- Toolchain/core bring-up checks: confirm `riscv-gnu-toolchain` produces a working `.elf` for cv32e40x's ABI, and confirm the cloned OpenHW core + its example CV-X-IF coprocessor builds and runs a trivial program under Verilator before wiring in any custom logic.
