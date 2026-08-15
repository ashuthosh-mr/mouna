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
- First cross-validated measurement (8x8 int matmul, `rdcycle`-timed,
  measurement window verified via disassembly to contain only the kernel):

  | | cycles |
  |---|---|
  | Spike ISS (instruction count, not timing) | 4085 |
  | CV32E40X RTL (Verilator, real cycles) | 6356 |

  The ~1.56x gap is exactly why a microarchitectural model is needed --
  Spike's count is not a usable proxy for real core timing on its own.

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
