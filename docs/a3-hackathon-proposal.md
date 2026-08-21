# Granularity-Aware Co-Design: Deciding *What Kind* of Hardware to Build, Before Building It

**Track:** domain-specific architecture co-design
**Target:** CVA6 (6-stage in-order; a Chipyard tile, and ESP's `ariane` CPU tile)

## The gap

CHIA already has both ends of the granularity spectrum. `examples/riscv_extensions`
has an agent implement RISC-V extensions in RTL, verified by `riscv_dv_gen_node` and
`cosim_node`'s Spike/Verilator lockstep. `examples/esp_accel_loop` has an agent
implement a DMA-driven ESP accelerator tile in HLS C++, validated in full-SoC
simulation.

**Neither chooses.** CS2 is handed a published spec (Bitmanip, Crypto, Zicond); the
ESP loop is handed "implement memcpy." Nothing derives a candidate from an
application, and nothing decides *at what granularity* the work should be
accelerated. `chia/simulators/` holds only `gem5.py` and `champsim.py`, so there is
no cheap stage capable of making that call; Spike appears only as lockstep
verification, never as a trace source for analysis.

We propose the missing decision stage: **one trace, one model, three routes.**

## The loop

```
app ──▶ spike -l trace ──▶ discover hot regions & fusable sequences
                                      │
                              classify by granularity
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
   1-2 instr, ALU              3+ instr, ALU/mem            loop nest / kernel
   native decoder edit         CV-X-IF coprocessor          ESP accelerator tile
   offload cost: 0             offload cost: ~2 cyc         cost: DMA + cfg + sync
        │                             │                             │
        └────────── agent writes RTL / HLS (existing CHIA nodes) ────┘
                                      │
                    verify (cosim_node, riscv_dv) ─▶ measure (verilator_run_node)
                                      │
                            calibrate: predicted band vs measured
```

The routing rule is derived from measurement, not intuition. We have measured each
offload cost on real RTL: an in-pipeline custom instruction retires in **1 cycle**;
a CV-X-IF offload costs **2**, which is why a 2-instruction fusion is break-even by
construction and we measured one at **exactly zero speedup**. Coarse-grained offload
pays only when the kernel is large enough to amortise DMA, configuration and
synchronisation.

## The non-obvious part: coarse acceleration creates fine-grained work

For a coarse accelerator, speedup is **not** set by the accelerator's throughput. It
is set by the *residual* core cost — data marshalling, configuration, synchronisation.
Real accelerator code makes this concrete: PULP's MAGIA/RedMulE tests move operands
with loops like `for (i..) mmio16(X_BASE + 2*i) = x_inp[i]` — thousands of iterations
of address arithmetic and stores, on the core, before the GeMM engine even starts.

That residual is exactly what our stall breakdown and candidate finder measure. So
the same trace and model that pick a custom instruction also predict whether a coarse
accelerator will pay — and the two answers interact: offloading a kernel often
*creates* the marshalling loop that then wants a post-increment or indexed-load
instruction. Reporting that interaction is the scientific contribution; it is a
co-design loop in the literal sense, and neither existing CHIA case study can express
it.

## Why this is credible

Run end to end already, outside CHIA, on two OpenHW in-order cores (CV32E40P/X);
open source. An analytical cycle model derived from the cores' manuals — not fitted —
lands within **0.25%** of Verilator RTL across 14 points, always over-predicting
(CHIA's `gem5_align` reaches 3% / 6.12% by having an agent tune gem5 against BOOM).
Four discovered custom instructions were implemented in RTL and measured; every
measured saving fell **inside** its predicted band. Two upstream `core-v-verif` bugs
were found on the way, one of which made every store and load silently return zero.

## Results we expect to report, including the negative ones

Beyond routing accuracy and RTL attempts avoided, the findings we think matter most
are the **failure modes a naive agentic loop reports as wins**, both already measured:

- **Interface cost erases short fusions.** A correct CV-X-IF multiply-accumulate —
  top-ranked under naive scoring — won **zero cycles**.
- **Fusion can cancel itself.** Removing instructions removes scheduling slack; one
  instruction we added won **zero**, because the compiler then placed a load directly
  into the fused operand and the new stall offset the instruction removed.

Both are the shape of result an agent would confidently claim as success. Our screening
node emits a *band* rather than a point estimate to surface exactly this, and the
calibration stage measures how often the band held.

## Scope and risk, stated plainly

**What we will demonstrate in three weeks:** the classifier and screening model across
all three tiers (cheap — it is analysis), the native and CV-X-IF routes end to end on
CVA6 (we have already done both on CV32E40P/X), and **one** coarse-grained case
through `esp_accel_loop`. The framework supports more; we will not claim to have run
more.

**Two risks we are not hiding.** Our 0.25% came from pipelines with a zero-wait-state
memory system; CVA6 has L1 caches, an MMU, and a scoreboard permitting out-of-order
writeback, so that figure will not transfer and we will compose the pipeline model with
`gem5.py`/`champsim.py` for the memory system rather than pretend otherwise. And
`esp_accel_loop` validates via Xcelium; if commercial EDA access is unavailable, the
coarse-grained route will be reported as predicted-only, with the two RISC-V routes
carrying the measured results.

## Cost

| item | estimate |
|---|---|
| LLM API — RTL/HLS generation and repair, ~10-15 candidates across three tiers | $250 |
| GCP CPU — Chipyard/Verilator builds, Spike traces, benchmark runs | $150 |
| Contingency — verification retries | $100 |
| **Total** | **~$500** |

Discovery, screening and calibration are Spike, Python and Verilator: cheap CPU only.
No FPGA hours are required for the routing claim.

## Deliverables

An open-sourced CHIA loop; a discovery node and a granularity-aware screening node
written to be reusable independently of our core choice (a new `chia/simulators/`
entry alongside gem5 and champsim); the CVA6 pipeline model; and a 4-page paper
reporting routing accuracy, compute avoided, the fine/coarse interaction, and the full
calibration record of predicted bands versus measured results.
