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

### Milestone 3 (in progress): finding custom-instruction candidates

`model/find_candidates.py` mines a trace for straight-line sequences worth
fusing into one custom instruction, scoring each with the same validated cycle
model. Candidates are constrained to what CV-X-IF can actually accept: no
control flow inside, at most `X_NUM_RS` register-file sources, one live-out
result, and (by default) no memory ops, since offloading those needs the
optional `xif_mem` interface.

On Embench `matmult-int` (97,748 instrs / 134,546 cycles):

| constraint | best candidate | execs | cycles saved |
|---|---|---|---|
| ALU only | `mul; addi; add` (a multiply-accumulate) | 399 | 1,197 (**0.9%**) |
| memory allowed | `addi; add; sw` (post-increment store) | 7,999 | 15,998 (**11.9%**) |
| memory allowed | `add; sw` (indexed store) | 8,000 | 8,000 (5.9%) |
| memory allowed | `add; lbu` (indexed load) | 3,200 | 3,200 (2.4%) |

The finder independently rediscovers what PULP put in Xpulp. ALU-only fusion is
worth under 1% and is not worth building hardware for; the real wins are in
**memory addressing** -- post-increment and indexed load/store, exactly
Xpulp's `p.lw rd, imm(rs1!)`. This agrees with the stall breakdown, which
already said arithmetic was not the bottleneck.

It also exposes a limit of the interface itself: the largest single cost,
branch/jump flush (8-25% of cycles), **cannot** be recovered through CV-X-IF at
all. CV-X-IF offloads instructions; a zero-overhead hardware loop changes how
the core fetches, so it has to live inside the pipeline. That is presumably why
Xpulp implemented hardware loops in the core rather than behind an interface.

#### Coprocessor: it works, and it teaches something the model got wrong

`rtl/pg_xif_mac.sv` implements the top compute-only candidate (`pg.mac`, a fused
multiply-accumulate) as a real CV-X-IF coprocessor, wired in behind
`+define+PARAGATO_XIF_MAC` with `X_EXT=1, X_NUM_RS=3`. It computes correctly --
the offloaded and baseline builds agree on the result -- and the core no longer
stalls.

But the measured speedup is **zero**:

  | build | cycles | result |
  |---|---|---|
  | baseline (`mul` + `add`) | 13,321 | 1 |
  | `pg.mac` over CV-X-IF | 13,321 | 1 |

The model predicted fusing `mul; add` would save one cycle per execution. It
does remove one instruction from the loop. The saving does not materialise
because **the offload itself costs a cycle**: the result has to be registered
and handed back over `result_valid`/`result_ready`, so `pg.mac` retires in 2
cycles where `mul; add` took 2. Fusing two single-cycle instructions across
CV-X-IF is break-even by construction.

This is a real limitation of the scoring, not of the hardware, and it is the
most useful thing the exercise produced:

- **The candidate finder over-values short fusions.** It scores a fused
  candidate at 1 cycle. It must instead charge the interface round-trip, which
  means a 2-instruction fusion can never win and a sequence must be *at least 3
  cycles* before CV-X-IF offload pays for itself.
- **It explains Xpulp's design.** PULP put post-increment load/store and
  hardware loops *inside* the pipeline rather than behind an extension
  interface. In-pipeline ops have no offload latency to amortise; that is
  exactly the cost measured here.
- Combined with the earlier finding that branch flush (the largest single cost)
  is unreachable through CV-X-IF at all, the honest conclusion for this core is
  that CV-X-IF suits *multi-cycle* compute offload, not fine-grained fusion.

Two CV-X-IF subtleties found by building it, both worth knowing:

1. The third operand comes from `instr[31:27]`, so a 3-input custom instruction
   must be encoded **R4-type** with the accumulator in `rs3`. It is *not* read
   back from `rd`.
2. `result_valid` must be **registered and held until `result_ready`**.
   Asserting it combinationally alongside `issue_valid` offers and withdraws the
   result in one cycle; the core never sees the instruction complete and the
   pipeline hangs forever.

#### Corrected candidate ranking

Feeding the measured offload latency back into the finder
(`--offload-latency 2`, the default now) prunes the candidate list from 33 to
11: every 2-instruction fusion is correctly rejected as break-even or worse.
What survives on `matmult-int` are the longer memory-addressing sequences:

| saved | %total | execs | len | pattern |
|---|---|---|---|---|
| 7,999 | **5.9%** | 7,999 | 3 | `addi; add; sw` -- post-increment store |
| 6,400 | **4.8%** | 3,200 | 4 | `lbu; add; addi; sb` -- load-modify-store |
| 3,200 | 2.4% | 3,200 | 3 | `add; addi; sb` -- indexed store |
| 798 | 0.6% | 399 | 4 | `addi; mul; addi; add` -- multiply-accumulate |

So the approach still finds real wins -- they are just the 3-4 instruction
memory-addressing patterns, not the short arithmetic fusions, and the
multiply-accumulate that looked best under the naive scoring drops to 0.6%.
That is the same conclusion Xpulp reached, now derived from measurement on this
core rather than assumed.

#### Post-increment store (`pg.swpi`): written, not yet working

`rtl/pg_xif_swpi.sv` implements the top candidate under corrected scoring --
`mem[rs1] <- rs2; rd <- rs1 + 4` -- as a CV-X-IF coprocessor using the optional
`xif_mem` interface (an FSM: issue -> memory request -> memory result ->
register writeback, since it both stores and updates the pointer).

Status: elaborates, and the baseline binary runs correctly on the X_EXT core
(`bench_swpi.c`: 6,203 cycles, result 3,584). The offloaded version hangs. The
`xif_mem` handshake is not right yet; the most likely cause is that the
coprocessor drives its memory request without regard to `commit_valid`, so a
request may be issued for an instruction the core has not committed. Not yet
diagnosed properly.

Worth recording from the spec while here: the CV32E40X manual states plainly
that **control-transfer instructions (branches and jumps) are not supported via
the eXtension interface**. That confirms from the documentation what the stall
breakdown implied -- the single largest cost on these kernels is structurally
out of reach for any CV-X-IF coprocessor.

### What CV32E40P shows, and whether CV32E40X was the right target

CV32E40P implements post-increment load/store natively. Its decoder sets *two*
register-file write enables for a single instruction:

    regfile_mem_we = 1    // loaded data  -> rd    (memory writeback port)
    regfile_alu_we = 1    // rs1 + offset -> rs1   (ALU writeback port)

That needs a dual-write-port register file, which CV32E40P has. The consequence
for anything built over CV-X-IF:

- **Post-increment store** needs only one writeback (a store returns no data,
  so only the pointer is written). It *is* expressible over CV-X-IF.
- **Post-increment load** needs two arbitrary register writes. CV-X-IF provides
  one; `dualwrite` writes `rd` and `rd+1`, not `rs1`. So `p.lw` **cannot be
  expressed over CV-X-IF at all** and has to live inside the pipeline.

Together with the two other limits measured here -- ~2 cycles of offload latency
per instruction, and control-transfer instructions being unsupported over the
interface by specification -- the picture is consistent: **CV-X-IF is built for
coarse-grained, multi-cycle compute offload, not for fine-grained ISA
extension.** Xpulp's post-increment addressing and hardware loops are in the
pipeline because that is the only place they can be.

So was CV32E40X the wrong choice? For the original goal -- *make one application
fast by adding custom instructions* -- CV32E40P would have been the better
vehicle, and the evidence for that is exactly what this project measured. But
the CV32E40X work is what produced the evidence, plus a validated cycle model,
the extension-selection result, and a stall breakdown that are all core-agnostic.
The natural next step reuses all of it: **use the model to predict Xpulp's
benefit on CV32E40P and validate against its RTL**, exactly as was done for Zbb
on CV32E40X (predicted to 2.7%).

### Where the cycles go

The model reports not just a cycle count but *why* those cycles were spent,
decomposing `cycles = compute (IPC=1 ideal) + stalls by microarchitectural
cause`. A raw cycle count from RTL cannot tell you this.

| benchmark | cycles | IPC | compute | branch flush | target misalign | jump flush | load-use |
|---|---|---|---|---|---|---|---|
| `matmult-int` | 134,546 | 0.73 | 72.7% | 16.6% | 8.3% | 2.4% | - |
| `primecount` | 3,927,267 | 0.58 | 57.9% | 23.7% | 5.7% | 1.7% | 11.1% |
| `edn` | 65,190 | 0.76 | 75.7% | 14.7% | 6.9% | 1.4% | 1.3% |
| `crc32` | 30,764 | 0.80 | 80.0% | 6.7% | 6.7% | 6.7% | - |
| `md5sum` | 72,497 | 0.73 | 72.6% | 17.0% | 3.6% | 6.8% | 0.0% |
| `statemate` | 1,639 | 0.71 | 70.7% | 13.3% | 5.8% | 5.8% | 4.4% |
| `tarfind` | 118,587 | 0.45 | 45.4% | 17.2% | 9.1% | 9.1% | 0.4% |

Two things fall straight out of this:

- **Control flow, not arithmetic, is the bottleneck.** Branch and jump flushes
  cost 8-25% of all cycles on every kernel. On this 4-stage pipeline a taken
  branch costs 3 cycles and resolves in EX, so there is no branch predictor to
  hide it.
- **`target_misalign` is free money.** 3.6-9.1% of cycles are lost purely
  because a branch target happens to be a non-word-aligned 32-bit instruction,
  which costs the pipeline an extra cycle. On `edn` that is 4,478 cycles --
  *larger than the 3,669 cycles won by enabling the whole bitmanip extension*.
  It needs no hardware change at all, only branch-target alignment from the
  compiler or linker.

This is the data a custom-instruction search needs: it says which cycles are
actually recoverable, and therefore which candidate instructions are worth
generating hardware for.

The breakdown is opt-in (`--breakdown`); the default output is just the cycle
count, which is all a design-space search loop needs. The stall attribution
itself is not the expensive part -- on `primecount` (2.3M instructions) trace
parsing takes ~10.0s versus ~3.0s for the whole model including stall
accounting, so the text-trace parser is what to optimise if throughput matters.

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
