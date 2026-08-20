# PARISCV v2

A pipeline for discovering profitable custom RISC-V instructions and validating
core/ISA configuration choices on real OpenHW cores (**CV32E40X** via CV-X-IF,
**CV32E40P** via decoder edits).

Two ingredients, combined:

1. **Fast filtering**: a Spike instruction trace + a parameterized
   microarchitectural model estimates real-core performance in seconds,
   without running RTL.
2. **Ground truth**: Verilator simulation of the real core confirms the
   model's predictions.

The goal: given an application, tell you the cheapest core configuration
(extensions, or a custom instruction) that runs it fastest -- in seconds via
the model, with RTL only needed to confirm the final answer.

See [`docs/plan.md`](docs/plan.md) for the full design rationale, prior-art
comparison, and a chronological bring-up log.

## TL;DR

| | status |
|---|---|
| Spike ISS | working -- compiles, runs, traces C programs |
| CV32E40X + Verilator | working (after fixing a real testbench bug, see below) |
| CV32E40P + Verilator | working |
| Cycle model | validated on both cores, 14 points, **worst case 0.25%**, typically under 0.01% |
| Predict a hardware change before building it | validated 3x: Zbb (-2.7%), Xpulp single-loop (-0.10%), Xpulp matmult (+15%, cause understood) |
| Discover + add + project a custom instruction | validated 4x on CV32E40P, all inside their predicted band |
| CV-X-IF custom instruction | works, but measured **zero** speedup -- the most useful negative result in this project |

Real bugs found along the way, listed in full further down: a `core-v-verif`
testbench wiring bug that made every CV32E40X store/load silently carry `0x0`;
a GCC bug that mis-orders nested hardware-loop registers on CV32E40P; and two
bugs in this project's own trace decoding -- one of which had been quietly
inflating a single benchmark's error by 3.45% since the beginning.

## Repo layout

```
setup.sh            Clones cv32e40x/cv32e40p/core-v-verif at pinned commits,
                     applies patches/, drops in rtl-tests/
patches/             Fixes to core-v-verif and to the cores' RTL, as patches
                     (not vendored in full)
rtl/                 Custom hardware: CV-X-IF coprocessors (CV32E40X)
rtl-tests/           Bare-metal CV32E40X test programs
model/               cv32e40x_model.py, cv32e40p_model.py (cycle models),
                     find_candidates.py (custom-instruction discovery),
                     predict_xpulp.py (predicting Xpulp before building it),
                     bench/ (kernel sources + build scripts for both cores)
bench/embench-iot/   Embench-IoT benchmark suite
tools/               Spike-side smoke tests, bare-metal assembly debug aids
docs/                Design plan and full chronological bring-up log
```

## Quickstart

```bash
./setup.sh   # clones cores/ and applies patches -- see setup.sh for pinned commits

# Spike ISS
riscv-none-elf-gcc -march=rv32imc_zicsr_zifencei -mabi=ilp32 -o prog.elf prog.c
spike --isa=rv32imac_zicntr_zicsr <rv32-pk> prog.elf

# CV32E40X + Verilator (see docs/plan.md for the full env-var explanation)
cd cores/core-v-verif/cv32e40x/sim/core
make veri-test TEST=pg_matmult CV_SW_TOOLCHAIN=<toolchain> CV_SW_PREFIX=riscv-none-elf- \
  CV_SW_MARCH=rv32imc_zicsr_zifencei SV_CMP_FLAGS="-Wno-COMBDLY" VERI_CFLAGS="-std=gnu++17 -O2" \
  VERI_CUSTOM=../../tests/programs/custom \
  SIM_TEST_PROGRAM_RESULTS=$PWD/results/test_program SIM_BSP_RESULTS=$PWD/results/bsp

# CV32E40P + Verilator: see model/bench/build_40p.sh and run_40p.sh
```

---

## Milestone 1: a cycle model validated on real RTL

`model/cv32e40x_model.py` consumes a Spike trace and predicts cycles from the
CV32E40X user manual's documented pipeline timings (per-instruction costs,
taken-branch/target-alignment penalties, load-use and `jalr` hazards).
`model/cv32e40p_model.py` subclasses it for CV32E40P, overriding only the
documented differences -- so that file doubles as a specification of how the
two cores differ:

| | CV32E40X | CV32E40P |
|---|---|---|
| `mulh`, `mulhsu`, `mulhu` | 4 | **5** |
| `fence`, `fence.i` | 5 | **2** |
| CSR access | 1 (4 for `jvt`) | **4** for `mstatus`/`mepc`/`mtvec`/`mcause`/`mcycle`/`minstret`/`mhpmcounter*`/`mcountinhibit`/`mhpmevent*`/debug CSRs, 1 otherwise |
| `jalr` data hazard | +1, or +2 after a load | **+1** after any producer |

Identical on both: integer ops, aligned load/store, `mul`, `div`/`rem`
(3 + leading zeros of the divisor), jump, branch taken/not-taken, and the +1
penalty for a non-word-aligned non-RVC control-flow target.

Per-instruction costs were independently calibrated against RTL
(`rtl-tests/pg_mulcost`, `rtl-tests/pg_xpulp_cal`): measured `add`=1, `mul`=1,
`mulh`=4/5, matching the manuals. `div`/`rem` cost 3..35 cycles depending on
the divisor; the model recovers the actual divisor by replaying
`spike --log-commits` register writes and charges `3 + leading_zeros(divisor)`
exactly.

### Validated on 7 Embench kernels x 2 cores

`LOCAL_SCALE_FACTOR=1` keeps RTL simulation tractable (scales repetitions only,
not the algorithm). Both cores' builds are constructed to have byte-identical
`.text` between the Spike-trace build and the RTL build -- see
[Why alignment matters](#why-alignment-matters) below for why this is required.

| benchmark | instrs | CV32E40X model | CV32E40X RTL | error | CV32E40P model | CV32E40P RTL | error |
|---|---|---|---|---|---|---|---|
| `matmult-int` | 97,748 | 134,543 | 134,545 | -0.00% | 134,543 | 134,547 | -0.00% |
| `primecount` | 2,273,871 | 3,927,222 | 3,927,224 | -0.00% | 3,927,222 | 3,927,226 | -0.00% |
| `edn` | 49,365 | 65,177 | 65,179 | -0.00% | 65,177 | 65,181 | -0.01% |
| `tarfind` | 53,846 | 117,147 | 117,149 | -0.00% | 117,147 | 117,151 | -0.00% |
| `md5sum` | 52,607 | 71,398 | 71,400 | -0.00% | 71,398 | 71,402 | -0.01% |
| `statemate` | 1,159 | 1,604 | 1,606 | -0.12% | 1,604 | 1,608 | -0.25% |
| `crc32` | 24,608 | 29,735 | 29,737 | -0.01% | 29,735 | 29,739 | -0.01% |

**Worst case 0.25%, typical under 0.01%.** The residual is now a small constant
few-cycle under-prediction (the boundary effect of the two `rdcycle`
instructions bracketing the measured region), not a systematic modelling error.

#### The bug that was hiding behind `crc32`

For most of this project `crc32` sat at **+3.45%** on *both* cores while
everything else was under 2%, and the fact that it was identical across two
different microarchitectures said the cause was in shared logic rather than in
either pipeline. It was, and it turned out to be a one-line bug with a long
reach.

`Insn.size` inferred instruction length from the *printed width of the hex
encoding* in the Spike trace -- 4 digits meaning 16-bit RVC, 8 meaning 32-bit.
But `spike -l` zero-pads RVC encodings to 8 digits as well:

    core   0: 0x80000008 (0x00001141) c.addi  sp, -16     <- 2 bytes, 8 digits

So **every compressed instruction in every trace was mis-sized as 4 bytes**,
for the entire project. It stayed dormant almost everywhere, because size only
feeds the branch-target alignment rule (a taken branch costs +1 cycle when its
target is a non-word-aligned **non-RVC** instruction). Wherever a hot branch
target was either word-aligned or genuinely 32-bit, the bug had no effect.
`crc32`'s hot loop happens to branch to a *compressed* instruction at a
non-word-aligned address -- which should cost nothing -- and was charged +1
cycle on all 1,023 iterations.

Now derived from the encoding's own low 2 bits, which RISC-V defines exactly
(`bits[1:0] != 11` means RVC):

| | before | after |
|---|---|---|
| `crc32` | +3.45% | **-0.01%** |
| worst case across 14 points | +3.45% | **0.25%** |

Two things worth drawing out. First, an earlier hypothesis for this residual
(RVC instructions having an implicit source operand the decoder dropped) was
tested and **ruled out** -- it was a real bug, and fixing it was correct, but it
changed none of the 14 results. Chasing the wrong cause first is the normal
shape of this kind of work. Second, the bug was only *found* because a new
benchmark (`bench_lbx.c`) happened to put a compressed instruction at a
misaligned branch target in its main loop, producing a 9% error that was far too
large to write off -- a reminder that widening the benchmark set is how latent
modelling bugs surface.

### What the model is (and is not) good for

It is **not** currently a speed win for a single run. On `primecount`
(3.9M cycles): Verilator ~5.7s vs Spike trace + model ~13s, dominated by the
Python parser chewing a >100MB text trace. The value is elsewhere:

1. **It scores hardware that does not exist yet.** A candidate custom
   instruction or extension config can be evaluated from an existing trace
   before anyone writes Verilog.
2. **One trace, many candidate designs.** Re-scoring under different
   microarchitectural assumptions costs seconds; each RTL configuration needs a
   rebuild plus a full re-simulation.
3. **It explains where cycles go**, not just how many there are.

### Where the cycles go

The model decomposes `cycles = compute (IPC=1 ideal) + stalls by
microarchitectural cause`.

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
  cost 8-25% of all cycles on every kernel. On a 4-stage pipeline a taken
  branch resolves in EX and costs 3 cycles; there is no branch predictor to
  hide it.
- **`target_misalign` is free money.** 3.6-9.1% of cycles are lost purely
  because a branch target happens to land on a non-word-aligned 32-bit
  instruction. On `edn` that is 4,478 cycles -- *larger than the 3,669 cycles
  won by enabling the entire bitmanip extension* (below). It needs no hardware
  change at all, only branch-target alignment from the compiler or linker.

This is exactly the data a custom-instruction search needs: it says which
cycles are actually recoverable, and by what kind of change.

(`--breakdown` on `cv32e40x_model.py`; printed by default on
`cv32e40p_model.py`.)

### Why alignment matters

On both cores a taken branch costs 3 cycles, or 4 when its target is a
non-word-aligned, non-RVC instruction. Two builds of the same C source, linked
at different base addresses, place loops at different alignments and
therefore genuinely execute at different cycle counts -- we measured 5,844 vs
6,356 cycles for the *same algorithm* on CV32E40X early on. A model trace and
its RTL ground truth must come from binaries with **byte-identical code
layout**, not merely identical source. `model/bench/` builds each kernel twice
(Spike at a high address, RTL at the core's boot address) with all data
sections pinned to matching absolute addresses, so `.text` comes out identical
regardless of `.text`'s own base -- and every build script verifies this
automatically before reporting a number.

---

## Milestone 2: predicting a hardware change before building it

Demonstrated on two cores, two different kinds of change:

| change | core | predicted | measured | error |
|---|---|---|---|---|
| enable Zbb bitmanip | CV32E40X | 3,570 cycles saved | 3,669 | **-2.7%** |
| enable Xpulp (single loop) | CV32E40P | **3.243x** speedup | **3.241x** | **-0.10%** |
| enable Xpulp (8x8 matmult, nested loops) | CV32E40P | **1.305x** speedup | **1.502x** | +15% (cause understood) |

### Zbb on CV32E40X

Embench `edn`, enabling `B_EXT = ZBA_ZBB_ZBS` (`+define+PARAGATO_ZBA_ZBB_ZBS` at
Verilator compile time -- the stock testbench hardwired the core's defaults;
see `patches/`), plus `-march=...zba_zbb_zbs` so the compiler emits
`sext.h`/`zext.h`/`sh1add`:

| | model | RTL | error |
|---|---|---|---|
| baseline (`B_EXT = B_NONE`) | 65,190 | 65,179 | +0.02% |
| with Zbb | 61,620 | 61,510 | +0.18% |
| **cycles saved** | **3,570** | **3,669** | **-2.7%** |

Both builds return the same benchmark result. The model predicted the benefit
of enabling bitmanip to within 2.7%, from a Spike trace alone, before the
bitmanip hardware was switched on.

### Xpulp on CV32E40P

Spike cannot execute Xpulp at all, so its binary cannot simply be traced.
`model/predict_xpulp.py` instead transforms the *baseline* trace analytically
-- converting counted loops to hardware loops, folding address arithmetic into
post-increment load/store, fusing `mul`+`add` into `p.mac` -- then re-costs it
with the validated CV32E40P model.

**No LLVM needed.** The PULP GCC 7.1.1 fork at
`~/revolution/bin/riscv32-unknown-elf-gcc` emits all of this from plain
`-O2 -march=rv32im[c]xpulpv2`: no intrinsics, no pragmas, no source changes.

Measured on RTL:

| kernel | baseline | Xpulp | speedup |
|---|---|---|---|
| single-loop MAC (hardware loops + post-inc + `p.mac`) | 13,323 | **4,111** | **3.24x** |
| 8x8 matmult (post-inc + `p.mac`, no hardware loops) | 6,848 | **4,559** | **1.50x** |

`p.mac` was calibrated against RTL at **1 cycle**, identical to `add`
(`rtl-tests/pg_xpulp_cal`) -- the direct counterpart to the CV-X-IF result
below, where the *same operation* offloaded over an interface cost 2 cycles and
won nothing. This is the clearest evidence for why Xpulp lives in the pipeline.

#### Three real bugs found getting here

1. **GCC mis-orders nested hardware loop registers.** CV32E40P requires
   `HWLoop[1].end >= HWLoop[0].end + 8` (asserted in `cv32e40p_controller.sv`),
   with loop 0 the *inner* loop. GCC 7.1.1 emits `lp.setupi x0` for the outer
   loop and `x1` for the inner -- backwards -- so any nested hardware loop
   violates the constraint and the core traps. Single-level hardware loops work
   perfectly (3.24x above). Worked around with `-mnohwloop` for nested code.
2. **RVC instructions have an implicit source operand this project's model was
   dropping.** Spike prints `c.addi a5, 4` and `c.add a4, a5`, but these mean
   `a5 = a5 + 4` and `a4 = a4 + a5` -- the destination is *also* a source.
   `decode_regs` was losing that, and with it real RAW dependencies. Fixed --
   but honestly, this changed none of the 14 benchmark results above, so it is
   **not** the cause of `crc32`'s residual.
3. **A custom instruction was silently squatting on a real opcode.** `pg.add3`
   (see Milestone 3) claimed opcode `7'h7b` outright -- that is
   `OPCODE_HWLOOP`, not free space -- so it broke every `lp.*` instruction the
   moment Xpulp was enabled. Moved into `funct3=3'b110`, the one sub-slot that
   opcode's own case left unused.

Also: the manual forbids compressed (RVC) instructions inside a hardware-loop
body, but `-march=rv32imcxpulpv2` emits them there anyway -- the backend does
not enforce it -- causing a trap. Dropping `c` avoids it.

#### Limit of the approach, stated plainly

The matmult prediction is +15% off, and the cause is understood: recompiling
for an extension **relays out the code**, and CV32E40P's taken-branch cost
depends on target alignment. The predictor works from the baseline layout and
cannot know the new one, so it reports an explicit uncertainty band rather than
false precision.

More fundamentally, Xpulp's largest win on matmult is not instruction fusion
but **induction-variable strength reduction** -- GCC restructures index-based
addressing (`mv; add; lw` recomputed per iteration) into pointer-walking
(`p.lw rd, 4(p!)`) *because* post-increment exists. Predicting an ISA extension
therefore means modelling the compiler's response to it, not just the
hardware's. The predictor handles both shapes explicitly, which is why it
mostly works, but it is a real bound on any claim to predict arbitrary ISA
changes from a single baseline trace.

---

## Milestone 3: discover, add, project and verify a custom instruction

### First attempt: CV-X-IF on CV32E40X (negative results, still useful)

`model/find_candidates.py` mines a trace for straight-line sequences worth
fusing into one instruction, constrained to what CV-X-IF can accept (no
control flow inside, at most `X_NUM_RS` register sources, one live-out result).
On `matmult-int`, ALU-only fusion tops out under 1% -- not worth building
hardware for.

**Built anyway, to check:** `rtl/pg_xif_mac.sv`, a CV-X-IF coprocessor for the
top ALU candidate (`pg.mac`, fused multiply-accumulate). It computes correctly,
but:

| build | cycles | result |
|---|---|---|
| baseline (`mul` + `add`) | 13,321 | 1 |
| `pg.mac` over CV-X-IF | 13,321 | 1 |

**Zero speedup.** The offload itself costs a cycle: the result must be
registered and handed back over `result_valid`/`result_ready`, so `pg.mac`
retires in 2 cycles where `mul; add` took 2. Fusing two single-cycle
instructions across CV-X-IF is break-even by construction -- a 2-instruction
fusion can never win; a sequence needs to be *at least 3 cycles* before offload
pays for itself. Feeding the measured 2-cycle offload latency back into the
finder prunes 33 viable candidates on `matmult-int` down to 11, all
memory-addressing sequences of length 3-4 (post-increment/indexed
load/store, 2.4-11.9%) -- exactly what Xpulp implements, now derived from
measurement rather than assumed.

A second attempt, `rtl/pg_xif_swpi.sv` (post-increment store, the top corrected
candidate), is written but hangs -- the `xif_mem` handshake is not right and
was not fully diagnosed. Two CV-X-IF subtleties learned along the way: a
3-operand instruction must be **R4-type** with the third operand in `rs3`
(`instr[31:27]`, not read back from `rd`); and `result_valid` must be
**registered and held** until `result_ready`, not asserted combinationally, or
the instruction never appears to complete and the pipeline hangs forever.

**Why CV32E40X was not the ideal target for this milestone:** CV32E40P
implements post-increment load/store *natively*, setting two register-file
write enables per instruction (`regfile_mem_we` for the loaded data,
`regfile_alu_we` for the updated pointer) -- something CV-X-IF's single
writeback cannot express at all for a *load*. Combined with the ~2-cycle
offload penalty and the manual's own statement that control-transfer
instructions are unsupported over CV-X-IF, the honest conclusion is that
**CV-X-IF suits coarse-grained compute offload, not fine-grained ISA
extension** -- which is exactly why Xpulp lives in the pipeline rather than
behind an interface.

### Proof of mechanism: a native instruction on CV32E40P

`patches/cv32e40p-pg-custom-instructions.patch` adds `pg.add3 rd, rs1, rs2 =
rs1 + rs2` by a plain decoder edit (opcode `7'h7b`, funct3=`000`):

| build | cycles | result |
|---|---|---|
| control (plain `add`) | 652 | 0 |
| `pg.add3` | 652 | 0 |

Identical cycle count is the point: an in-pipeline custom instruction is
genuinely single-cycle, with **no offload penalty** -- unlike the CV-X-IF MAC
above. Adding it needed only one decode arm (`regfile_alu_we`, `rega_used_o`,
`regb_used_o`, `alu_operator_o`, clear `illegal_insn_o`) -- no pipeline,
register-file, or LSU changes for an ALU-shaped instruction.

Two traps hit while doing this: `core-v-verif` clones its **own** copy of the
core RTL into `core-v-cores/` and re-runs `git checkout <pinned-sha>` on every
build, so patching the standalone `cores/cv32e40p` checkout has no effect on
what is simulated -- and the pinned revision predates the
`OPCODE_CUSTOM_0..3` naming, using `OPCODE_PULP_OP` (`0x5b`)/`OPCODE_VECOP`
(`0x57`) instead, which is what left `0x7b` free. Also: deleting that clone's
`.git` to "protect" local edits breaks the build outright -- unnecessary, since
the clone is already at the pinned sha and the checkout is a no-op that leaves
edits intact.

### Discovery, native addition, and projection: three instructions, one scoreboard

The full loop, repeated three times on benchmarks and idioms **the tool picked,
not hand-selected for the answer**: `find_candidates.py --core 40p --native`
mines a baseline trace; the found instruction is added to the core with its
own ALU datapath; its benefit is projected from the baseline trace (Spike
cannot execute any of these either); then measured on RTL.

| instruction | idiom | source benchmark | baseline model check | saving predicted (band) | saving measured |
|---|---|---|---|---|---|
| `pg.idx` = `rs2 + ((rs1&0xff)<<2)` | table-index `andi;slli;add` | crc32 | 13,323 model vs 13,326 RTL (-0.02%) | 1,024..2,048 | **2,048** (optimistic end) |
| `pg.rol` = `rol(rs1,rs2)` | variable rotate `sll;sub;srl;or` | md5sum | 16,392 model vs 16,395 RTL (-0.02%) | 2,046..3,069 | **2,048** (pessimistic end) |
| `pg.sha` = `(rs1>>>15)+rs2` | fixed-shift `srai;add` | edn | 14,344 model vs 14,347 RTL (-0.02%) | 0..1,024 | **0** (pessimistic end) |
| indexed load `rd = *(rs1+rs2)` | `add;lbu` | matmult-int | 10,249 model vs 10,253 RTL (-0.04%) | 0..2,046 | **1,024** |

All three compute correctly (identical results to their baselines). `pg.idx`'s
saving was exact. The other two show the same real mechanism, at different
strengths: **fusing removes instructions, and with them the scheduling slack
that was hiding a load-use hazard.** After recompiling, GCC rescheduled the
shorter loop so that a just-loaded value fed directly into the fused
instruction -- something the original, longer schedule had avoided by
accident. Feeding the exposed hazard back into the cycle model recovers the
right answer in both cases (`pg.rol`: 14,344 predicted vs 14,347 measured,
-0.02%; `pg.sha`: same). The *cycle model* is right in all three cases; what
varies is the *candidate scorer's* blindness to a schedule that does not exist
yet.

`find_candidates.py` now reports this as a **band**, not a single number: the
optimistic end assumes the original schedule survives fusion, the pessimistic
end assumes a hidden load-use hazard is exposed. Every measured result above
landed inside its band.

### Fourth instruction: one that needed no new hardware at all

The finder's top candidate on `matmult-int` with memory allowed is `add; lbu` --
an indexed byte load, `rd = *(rs1+rs2)`. Unlike the three above, this needed
**no RTL change whatsoever**: CV32E40P's Xpulp mode already implements a native
register-register indexed load (opcode `LOAD`, `funct3=111`, `funct7=0100000`
for byte-unsigned). So this validates the finder against hardware that already
existed, rather than hardware built to match what the finder asked for.

| | measured |
|---|---|
| baseline (`add` then `lbu`) | 10,253 |
| native indexed load | **9,229** |
| cycles saved | **1,024** |

Same result both ways. The saving landed inside the predicted band.

**One honest correction from this experiment.** The first measurement showed
*exactly zero* speedup, and the cause was my benchmark, not the instruction: I
declared the inline-asm output as `uint8_t`, so GCC emitted a redundant
`zext.b` -- cancelling the instruction the fusion had saved. `funct7=0x20` is
the *unsigned* byte form and already zero-extends. Declaring the output
`uint32_t` removed the `zext.b` and the expected 1,024 cycles appeared. Worth
recording because it is an easy way to accidentally measure zero and conclude an
instruction is worthless.

### How much of this is actually validated

Being explicit, because these claims are not all equally strong:

| claim | evidence |
|---|---|
| cycle model accuracy | 14 points (7 kernels x 2 cores), worst case 0.25%, typically under 0.01% |
| predicting an existing extension's benefit | 3 points: Zbb (-2.7%), Xpulp single-loop (-0.10%), Xpulp matmult (+15%, cause understood) |
| discover + add + project a custom instruction | 4 points, all inside their predicted band, on tool-picked idioms |

The **model** is the strongly validated part. **Projecting a change** is
thinner, and every miss so far shares one root cause: **recompiling for a new
instruction or extension lets the compiler relay out and reschedule the code,
and a baseline trace cannot show what it will do.** That is a real bound on
this class of tool, not a bug to be fixed away -- and it is a large part of why
building the actual hardware and measuring, rather than trusting the model
end-to-end, is what caught it.

---

## Prior art

Closest comparable: CIDRE (arXiv 2509.15782). Also relevant: OpenASIP, ARISE,
Longnail/CoreDSL, GenIE, MARVEL. None ship as a maintained, installable tool
targeting a real, community-adopted core via its standard extension interface
(CV-X-IF) or by direct core modification -- that's the gap this project
targets.
