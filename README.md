# PARISCV v2

A pipeline for discovering profitable custom RISC-V instructions and validating
core/ISA configuration choices, targeting **OpenHW CV32E40X** via its **CV-X-IF**
extension interface.

Two ingredients, combined:

1. **Fast filtering**: a Spike instruction trace + a parameterized
   microarchitectural model estimates CV32E40X performance in seconds, without
   running RTL.
2. **Ground truth**: Verilator simulation of the real CV32E40X core confirms
   the model's predictions and validates the final result.

The goal: given an application, tell you the cheapest CV32E40X-class core
configuration (extensions, and eventually CV-X-IF custom instructions) that
runs it fastest -- in seconds via the model, with RTL only needed to confirm
the answer.

See [`docs/plan.md`](docs/plan.md) for the full design rationale, prior-art
comparison (CIDRE, OpenASIP, ARISE, Longnail/CoreDSL, GenIE, MARVEL), and
bring-up log.

## Status

- **Spike ISS**: working end-to-end -- compiles, runs, and traces C programs.
- **CV32E40X + Verilator**: working end-to-end after fixing a real bug in
  core-v-verif's testbench (see `patches/`) -- `data_wdata_o`/`data_rdata_i`
  were never connected between the core and memory, so every store/load
  silently carried `0x0`.
- **Cycle model (Milestone 1)**: `model/cv32e40x_model.py` consumes a Spike
  trace and predicts CV32E40X cycles from the user manual's documented pipeline
  timings. Validated against RTL across Embench kernels with very different
  instruction mixes (`LOCAL_SCALE_FACTOR=1` keeps RTL simulation tractable; it
  scales repetitions only, not the algorithm):

  | benchmark | instrs | model | RTL (ground truth) | error |
  |---|---|---|---|---|
  | `matmult-int` | 97,748 | 134,546 | 134,545 | **+0.00%** |
  | `primecount` | 2,273,871 | 3,927,267 | 3,927,224 | **+0.00%** |
  | `edn` | 49,365 | 65,190 | 65,179 | **+0.02%** |
  | `tarfind` | 53,846 | 118,587 | 117,149 | +1.23% |
  | `md5sum` | 52,607 | 72,497 | 71,400 | +1.54% |
  | `statemate` | 1,159 | 1,639 | 1,606 | +2.05% |
  | `crc32` | 24,608 | 30,764 | 29,737 | +3.45% |

  Every error is an over-prediction, so the model is a consistent upper bound.
  Per-instruction costs were independently calibrated against RTL
  (`rtl-tests/pg_mulcost`): measured `add`=1, `mul`=1, `mulh`=4, matching the manual.

  `div`/`rem` cost 3..35 cycles depending on the divisor. The model recovers the
  actual divisor by replaying `spike --log-commits` register writes and charges
  `3 + leading_zeros(divisor)` exactly; this took `tarfind` (770 divides) from
  +4.51% to +1.23%.

### What the model is (and is not) good for

It is **not** currently a speed win for a single run. On `primecount`
(3.9M cycles): Verilator 5.7s vs Spike trace 2.1s + model 11.0s. The model's
Python parser chewing a 115 MB text trace dominates and is the obvious thing to
optimise.

The value is elsewhere:

1. **It scores hardware that does not exist yet.** RTL simulation requires RTL.
   A candidate custom instruction or extension config can be evaluated from an
   existing trace before anyone writes Verilog -- which is the entire point of
   the discovery pipeline.
2. **One trace, many candidate designs.** The instruction trace is captured
   once; re-scoring it under different microarchitectural assumptions costs
   seconds, whereas each RTL configuration needs a rebuild plus a full
   re-simulation.
3. **It explains where cycles go.** The model reports the instruction mix,
   branch-taken counts, hazards and stalls behind its estimate, which a bare
   cycle count from RTL does not give you.

### Milestone 2: predicting the benefit of a hardware change

The point of the model is to score a design *before* it is built. This is
testable on CV32E40X because its optional extensions are RTL parameters that
already exist -- so the model's prediction can be checked against real hardware.

Taking Embench `edn` and enabling the bitmanip extension (`B_EXT = ZBA_ZBB_ZBS`,
plus `-march=...zba_zbb_zbs` so the compiler emits `sext.h`/`zext.h`/`sh1add`):

  | | model | RTL | model error |
  |---|---|---|---|
  | baseline (`B_EXT = B_NONE`) | 65,190 | 65,179 | +0.02% |
  | with Zbb (`B_EXT = ZBA_ZBB_ZBS`) | 61,620 | 61,510 | +0.18% |
  | **cycles saved** | **3,570** | **3,669** | **-2.7%** |

Both builds return the same benchmark result, so the comparison is valid. The
model predicted the benefit of enabling bitmanip to within 2.7% -- from a Spike
trace alone, before the bitmanip hardware was switched on.

`B_EXT` is selected with `+define+PARAGATO_ZBA_ZBB_ZBS` at Verilator compile
time (the stock testbench hardwired the core's defaults; see `patches/`).

### Why alignment matters

Getting here required a methodological fix worth stating plainly. On CV32E40X a
taken branch costs **3 cycles, or 4 when its target is a non-word-aligned,
non-RVC instruction**. Two builds of the same C source, linked at different
base addresses, place the loop at different alignments and therefore genuinely
execute at different cycle counts -- we measured 5844 vs 6356 for the same
algorithm. A model trace and its RTL ground truth must therefore come from
binaries with identical code layout, not merely identical source. `model/bench/`
builds one source twice (Spike at 0x80000000, RTL at 0x0) with matched layout to
make the comparison valid.


## Layout

```
setup.sh          Clones cv32e40x/cv32e40p/core-v-verif at pinned commits,
                  applies patches/, drops in rtl-tests/
patches/          Our fixes to core-v-verif, as patches (not vendored in full)
rtl-tests/        Our own bare-metal CV32E40X test programs
bench/embench-iot/  Embench-IoT benchmark suite (source for future kernels)
tools/            Spike-side smoke tests, bare-metal assembly debug aids
docs/             Design plan and bring-up log
```

## Quickstart

```bash
./setup.sh   # clones cores/ and applies our patches -- see setup.sh for pinned commits

# Spike ISS
riscv-none-elf-gcc -march=rv32imc_zicsr_zifencei -mabi=ilp32 -o prog.elf prog.c
spike --isa=rv32imac_zicntr_zicsr <rv32-pk> prog.elf

# CV32E40X + Verilator (see docs/plan.md for the full env-var explanation)
cd cores/core-v-verif/cv32e40x/sim/core
make veri-test TEST=pg_matmult CV_SW_TOOLCHAIN=<toolchain> CV_SW_PREFIX=riscv-none-elf- \
  CV_SW_MARCH=rv32imc_zicsr_zifencei SV_CMP_FLAGS="-Wno-COMBDLY" VERI_CFLAGS="-std=gnu++17 -O2" \
  VERI_CUSTOM=../../tests/programs/custom \
  SIM_TEST_PROGRAM_RESULTS=$PWD/results/test_program SIM_BSP_RESULTS=$PWD/results/bsp
```

## Prior art

Closest comparable: CIDRE (arXiv 2509.15782). Also relevant: OpenASIP, ARISE,
Longnail/CoreDSL, GenIE, MARVEL. None ship as a maintained, installable tool
targeting a real, community-adopted core via its standard extension interface
(CV-X-IF) -- that's the gap this project targets.
