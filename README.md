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

### Adding a custom instruction to CV32E40P: works

CV32E40P has no extension interface, so a new instruction is added by editing
the decoder. `patches/cv32e40p-pg-add3-custom-insn.patch` adds one and it runs:

    pg.add3 rd, rs1, rs2    rd <- rs1 + rs2
    R-type, opcode 7'h7b (RISC-V custom-3), funct3 = 000, funct7 = 0000000

| build | cycles | result |
|---|---|---|
| control (plain `add`) | 652 | 0 |
| `pg.add3` (custom instruction) | 652 | 0 |

`result=0` means all 64 test inputs matched a plain `add`, so the instruction
computes correctly. The identical cycle count is the point: an in-pipeline
custom instruction is genuinely single-cycle, with **no offload penalty** --
unlike the CV-X-IF multiply-accumulate, which cost 2 cycles and therefore won
nothing. This is the concrete reason Xpulp lives in the pipeline.

Adding it required only: one decode arm setting `regfile_alu_we`,
`rega_used_o`, `regb_used_o`, `alu_operator_o` and clearing `illegal_insn_o`.
No pipeline, register-file or LSU changes for an ALU-shaped instruction.

Two traps worth knowing when doing this:

1. `core-v-verif` clones its **own** copy of the core RTL into `core-v-cores/`
   and runs `git checkout <pinned-sha>` on **every build**. Patching the
   standalone `cores/cv32e40p` checkout has no effect on what is simulated, and
   the pinned revision differs from `master` -- here it predates the
   `OPCODE_CUSTOM_0..3` naming and uses `OPCODE_PULP_OP` (`7'h5b`) and
   `OPCODE_VECOP` (`7'h57`), leaving `7'h7b` free.
2. Deleting that clone's `.git` to protect local edits **breaks the build**, as
   the checkout step then fails hard. Because the clone is already at the pinned
   sha, `git checkout` is a no-op that leaves working-tree edits intact, so
   local RTL changes survive rebuilds without any intervention.

### Ported to CV32E40P

`model/cv32e40p_model.py` is the same model retargeted to CV32E40P. It
subclasses the CV32E40X model and overrides only the documented timing
differences, so the file doubles as a specification of how the two cores differ:

| | CV32E40X | CV32E40P |
|---|---|---|
| `mulh`, `mulhsu`, `mulhu` | 4 | **5** |
| `fence`, `fence.i` | 5 | **2** |
| CSR access | 1 (4 for `jvt`) | **4** for `mstatus`/`mepc`/`mtvec`/`mcause`/`mcycle`/`minstret`/`mhpmcounter*`/`mcountinhibit`/`mhpmevent*`/debug CSRs, 1 otherwise |
| `jalr` data hazard | +1, or +2 after a load | **+1** after any producer |

Identical on both: integer ops, aligned load/store, `mul`, `div`/`rem`
(3 + leading zeros of the divisor), jump, branch taken/not-taken, and the +1
penalty for a non-word-aligned non-RVC control-flow target.

Validated against CV32E40P RTL on the same seven Embench kernels:

| benchmark | instrs | model | RTL (ground truth) | error |
|---|---|---|---|---|
| `matmult-int` | 97,748 | 134,546 | 134,547 | **-0.00%** |
| `primecount` | 2,273,871 | 3,927,267 | 3,927,226 | **+0.00%** |
| `edn` | 49,365 | 65,190 | 65,181 | **+0.01%** |
| `tarfind` | 53,846 | 118,587 | 117,151 | +1.23% |
| `md5sum` | 52,607 | 72,497 | 71,402 | +1.53% |
| `statemate` | 1,159 | 1,639 | 1,608 | +1.93% |
| `crc32` | 24,608 | 30,764 | 29,739 | +3.45% |

The spread matches CV32E40X almost exactly (0.00%-3.45% there, 0.00%-3.45%
here), and every error is again an over-prediction. `crc32`'s residual is the
same on both cores, which says it is a property of the shared modelling -- not
of either microarchitecture -- and so remains the most useful thing left to
chase.

Build/run flow for this core: `link_{rtl,spike}_40p.ld` (data pinned to matching
addresses, kept under 1 MB for this testbench), `build_40p.sh`, `run_40p.sh`.
Its testbench peripherals differ from CV32E40X (`0x10000000` print,
`0x20000004` exit), handled by `report_rtl_40p.c`.

## Milestone 2 complete: predicting Xpulp on CV32E40P

Milestone 2 -- *predict a hardware change's benefit before building it* -- is now
demonstrated twice, on two cores and two very different kinds of change:

| change | core | predicted | measured | error |
|---|---|---|---|---|
| enable Zbb bitmanip | CV32E40X | 3,570 cycles saved | 3,669 | **-2.7%** |
| enable Xpulp (single loop) | CV32E40P | **3.243x** speedup | **3.241x** | **-0.10%** |

The Xpulp case is the harder one: **Spike cannot execute Xpulp at all**, so the
extension's binary cannot simply be traced. `model/predict_xpulp.py` instead
transforms the *baseline* trace analytically -- converting counted loops to
hardware loops, folding address arithmetic into post-increment load/store, and
fusing `mul`+`add` into `p.mac` -- then re-costs it with the validated CV32E40P
model.

**No LLVM needed.** The PULP GCC 7.1.1 fork already present at
`~/revolution/bin/riscv32-unknown-elf-gcc` emits all of this from plain
`-O2 -march=rv32im[c]xpulpv2`: no intrinsics, no pragmas, no source changes.

### Measured Xpulp speedups (CV32E40P RTL)

| kernel | baseline | Xpulp | speedup |
|---|---|---|---|
| single-loop MAC (hardware loops + post-inc + `p.mac`) | 13,323 | **4,111** | **3.24x** |
| 8x8 matmult (post-inc + `p.mac`, no hardware loops) | 6,848 | **4,559** | **1.50x** |

`p.mac` was calibrated against RTL at **1 cycle**, identical to `add`
(`rtl-tests/pg_xpulp_cal`). That is the direct counterpart to the earlier
CV-X-IF result: the *same operation* offloaded over CV-X-IF cost 2 cycles and
won nothing, while in-pipeline it is free. It is the clearest evidence for why
Xpulp lives in the pipeline.

### Three real bugs found

1. **GCC mis-orders nested hardware loop registers.** CV32E40P requires
   `HWLoop[1].end >= HWLoop[0].end + 8` (asserted in
   `cv32e40p_controller.sv`), with loop 0 the *inner* loop. GCC 7.1.1 emits
   `lp.setupi x0` for the outer loop and `x1` for the inner -- backwards -- so
   any nested hardware loop violates the constraint and the core traps.
   Single-level hardware loops work perfectly (3.24x above). Worked around with
   `-mnohwloop` for nested code.

2. **RVC instructions have an implicit source operand the model was dropping.**
   Spike prints `c.addi a5, 4` and `c.add a4, a5`, but these mean
   `a5 = a5 + 4` and `a4 = a4 + a5` -- the destination is *also* a source.
   `decode_regs` was losing that, and with it real RAW dependencies. Fixed. Note
   honestly: this did **not** change any of the 14 benchmark results, so it is
   not the cause of `crc32`'s +3.45% residual, which remains unexplained.

3. **A custom instruction was silently squatting on a real opcode.** `pg.add3`
   claimed opcode `7'h7b` outright -- that is `OPCODE_HWLOOP`, not free space --
   so it broke every `lp.*` instruction the moment Xpulp was enabled. Moved into
   `funct3=3'b110`, the one sub-slot that opcode's own case leaves unused.

Also: the manual forbids compressed (RVC) instructions inside a hardware-loop
body, but `-march=rv32imcxpulpv2` emits them there anyway -- the backend does not
enforce it -- causing a trap. Dropping `c` avoids it.

### Limit of the approach, stated plainly

The matmult prediction is **+15%** off (predicted 5,252, measured 4,559), and the
cause is understood: recompiling for an extension **relays out the code**, and on
CV32E40P a taken branch costs 3 or 4 cycles depending on whether its target is
word-aligned. The predictor works from the baseline layout and cannot know the
new one, so it now reports an explicit uncertainty band rather than false
precision.

More fundamentally, Xpulp's largest win here is not instruction fusion but
**induction-variable strength reduction** -- GCC restructures index-based
addressing (`mv; add; lw` recomputed per iteration) into pointer-walking
(`p.lw rd, 4(p!)`) *because* post-increment exists. Predicting an ISA extension
therefore means modelling the compiler's response to it, not just the hardware's.
The predictor handles both shapes explicitly, and that is why it works, but it is
a real caveat on any claim to predict arbitrary ISA changes.

## Milestone 3 complete: discover, add, model and project a custom instruction

The full loop, end to end, on CV32E40P:

**1. Discover.** `model/find_candidates.py --core 40p --native` mines a baseline
Spike trace. On a table-driven CRC32 the top candidate is the table-address
sequence `andi; slli; add`, executed 1,024 times and worth 2,048 cycles (15.4%).
`--native` matters: an instruction added by editing the core retires in 1 cycle,
unlike a CV-X-IF offload which costs 2 and makes short fusions worthless.

**2. Add.** `pg.idx rd, rs1, rs2  ->  rd = rs2 + ((rs1 & 0xff) << 2)`, a real
custom instruction with its own ALU datapath
(`patches/cv32e40p-pg-custom-instructions.patch`):

  * `ALU_PGIDX` added to `alu_opcode_e` (a free encoding, `7'b0001110`)
  * one line of datapath in `cv32e40p_alu.sv`
  * one decoder arm at opcode `7'h7b`, `funct3=111`

Emitted from C with `.insn` -- no toolchain change, no intrinsics.

**3. Model and project.** Spike cannot execute `pg.idx` any more than it can
execute Xpulp, so the projection is made from the *baseline* trace: the model
costs the baseline, the finder scores the fusion, and the new performance is the
difference.

**4. Verify against RTL.**

| | projected | measured | error |
|---|---|---|---|
| baseline | 13,323 | 13,326 | **-0.02%** |
| with `pg.idx` | **11,275** | **11,278** | **-0.03%** |
| cycles saved | 2,048 | 2,048 | **0.00%** |

Both builds return the same CRC (`2083658589`), so the instruction is
functionally correct, and the projected saving was exact.

### Why this closes the loop

The three milestones now chain into one workflow that needs no hardware to exist
before it can answer "is this worth building?":

1. **Model** a core from its manual, validated to 0.00-3.45% on Embench across
   two different cores.
2. **Predict** the benefit of a change before building it -- Zbb on CV32E40X
   (-2.7%), Xpulp on CV32E40P (-0.10%).
3. **Discover** a custom instruction from a trace, project its benefit, add it
   to the core, and confirm (0.00% on the saving).

The negative results along the way are what make the positive one trustworthy:
the CV-X-IF multiply-accumulate that measured exactly zero speedup is why
`--native` exists and why the finder charges an interface round-trip when one is
present.

### Second custom instruction: validating the method, not just the instruction

The CRC result above is one data point on a benchmark and an instruction that
were both chosen with the answer in mind. A fairer test is a *different*
instruction shape, on an idiom taken from real Embench code, picked by the tool
rather than by hand.

`pg.rol rd, rs1, rs2` -- variable rotate-left -- came from
`find_candidates.py` ranking the `sll; sub; srl; or` idiom top on Embench
md5sum (4 instructions, 18.7% of cycles in a focused kernel). It reuses the
core's existing rotate-right datapath, since `rol(x,n) == ror(x,32-n)`:

| | projected | measured | error |
|---|---|---|---|
| baseline | 16,392 | 16,395 | **-0.02%** |
| with `pg.rol` | 13,323 | **14,347** | **-7.1%** |
| cycles saved | 3,069 | **2,048** | over-predicted by 1,024 |

Both builds return the same result, so the instruction is correct -- but the
projected *saving* was a third too high, and the reason is worth stating.

**Fusion removed the scheduling slack that was hiding a load-use hazard.**
In the baseline the loop reads

    lw   a4,0(a4)
    lw   a3,0(a3)
    addi a5,a5,4        <- separates the load from its consumer
    sll  a2,a4,a3

After fusing, GCC rescheduled the shorter loop and `pg.rol` landed *immediately*
after `lw a3`, so the hazard appeared: +1 cycle x 1024 = exactly the shortfall.
Feeding that back, 16,392 - 3,072 + 1,024 = 14,344 against 14,347 measured
(**-0.02%**) -- the cycle model was right all along; the *candidate scorer* was
optimistic because it costed the sequence in isolation.

`find_candidates.py` now reports a **band** rather than a single number. The
optimistic end assumes the schedule absorbs the fusion; the pessimistic end
assumes a hidden load-use hazard is exposed. Both measured results fall inside
it -- CRC at the optimistic end (2,048 of 1,024..2,048), rotate at the
pessimistic end (2,048 of 2,046..3,069). Which end applies depends on how the
compiler reschedules the shorter loop, which a baseline trace cannot show.

### How much of this is actually validated

Worth being explicit, because the numbers above are not all equally strong:

| claim | evidence |
|---|---|
| cycle model accuracy | 7 Embench kernels x 2 cores, 0.00-3.45%, always an upper bound |
| predicting an existing extension | 3 points: Zbb (-2.7%), Xpulp single-loop (-0.10%), Xpulp matmult (+15%) |
| discovering + adding + projecting a custom instruction | 2 points: `pg.idx` (0.00% on the saving), `pg.rol` (-33% on the saving, cause understood) |

The model itself is the well-validated part. Projecting a *change* is thinner,
and both misses so far (matmult alignment, `pg.rol` scheduling) share one root
cause: **recompiling for a new instruction lets the compiler relay out and
reschedule the code, and the baseline trace cannot show what it will do.** That
is a real bound on this class of tool, not a bug to be fixed away.

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
