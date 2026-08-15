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
  instruction mixes (all runs use `LOCAL_SCALE_FACTOR=1` to keep RTL simulation
  tractable; that scales repetitions only, not the algorithm):

  | benchmark | instrs | model | RTL (ground truth) | error |
  |---|---|---|---|---|
  | `matmult-int` | 97,748 | 134,546 | 134,545 | **+0.00%** |
  | `primecount` | 2,273,871 | 3,927,267 | 3,927,224 | **+0.00%** |
  | `edn` | 49,365 | 65,190 | 65,179 | **+0.02%** |
  | `md5sum` | 52,607 | 72,497 | 71,400 | +1.54% |
  | `statemate` | 1,159 | 1,639 | 1,606 | +2.05% |
  | `crc32` | 24,608 | 30,764 | 29,737 | +3.45% |
  | `tarfind` | 53,846 | 122,437 | 117,149 | +4.51% |

  Per-instruction costs were independently calibrated against RTL
  (`rtl-tests/pg_mulcost`): measured `add`=1, `mul`=1, `mulh`=4 cycles, all
  matching the manual.

  Every error is an over-prediction, i.e. the model is a consistent upper bound.
  `tarfind`'s outlier is fully explained: it executes 770 `div`/`rem`
  instructions, which cost 3-35 cycles depending on the divisor, and a Spike
  `-l` trace does not record operand values -- so the model charges the worst
  case and says so in its output. Recovering operand values (via
  `spike --log-commits`) is the obvious fix. `crc32`'s residual is ~1 cycle
  across ~1024 occurrences of a single event type and is not yet pinned down.

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
