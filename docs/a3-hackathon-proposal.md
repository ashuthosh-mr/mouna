# Granularity-Aware Co-Design: Deciding *What Kind* of Hardware to Build, Before Building It

**Target:** Rocket + RoCC + Gemmini in Chipyard — every tier measured under Verilator,
no commercial EDA
**Prior work:** open-source, already running end-to-end outside CHIA on two OpenHW cores

## Overview

CHIA has both ends of the granularity spectrum. `examples/riscv_extensions` has an
agent implement a RISC-V extension in RTL, verified by Spike/Verilator lockstep and
riscv-dv. `examples/esp_accel_loop` has an agent implement a DMA-driven accelerator
tile in HLS C++, validated in full-SoC simulation. **Neither chooses.** CS2 is handed a
published spec (Bitmanip, Crypto, Zicond); the ESP loop is handed "implement memcpy."
Nothing derives a candidate from an application, and nothing decides *at what
granularity* work should be accelerated. No cheap stage exists that could:
`chia/simulators/` holds only gem5 and champsim, and Spike appears only as lockstep
verification, never as a trace source. We propose the missing decision stage: **one
trace, one model, three routes** — in-pipeline decoder edit, RoCC coprocessor, or
Gemmini-class accelerator — chosen by measured break-even cost, not intuition.

## Methodology

```
app ─▶ spike -l ─▶ discover hot regions & fusable sequences ─▶ classify by granularity
                                        │
      ┌─────────────────────────────────┼─────────────────────────────────┐
      ▼                                 ▼                                 ▼
 1-2 instr, ALU                  3+ instr, ALU/mem                 loop nest / kernel
 Rocket decoder edit             RoCC coprocessor                  Gemmini (DMA +
 in-pipeline: ~1 cyc             offload: calibrate                scratchpad + config)
      │                                 │                                 │
      └──── agent writes Chisel (reusing chia/chipyard build+cosim) ──────┘
                                        │
       verify (Spike lockstep, riscv-dv) ─▶ measure (Verilator) ─▶ calibrate
```

Thresholds come from RTL measurement, not intuition. On CV32E40P an in-pipeline
custom instruction retires in **1** cycle while a CV-X-IF offload cost **2** — so a
two-instruction fusion is break-even by construction, and we measured one at
**exactly zero speedup**. We recalibrate the same break-even for RoCC on Rocket.
Because tiers 2 and 3 both attach over **RoCC**, the comparison isolates *granularity*
rather than confounding it with interface and toolchain.

**The contribution: coarse acceleration creates fine-grained work.** Speedup is set by
the *residual* core cost — marshalling, tiling, configuration — not accelerator
throughput. Gemmini makes this directly measurable, and is our validation target: its
ISA exposes both hand-tiled `mvin`/`matmul`/`mvout` loops and CISC `gemmini_loop_ws`,
whose `LoopMatmul` FSM exists, in its authors' words, because of "CPU and loop
overheads" — explicitly a performance enhancer adding no new functionality. Running
both is a controlled A/B on the residual, and asks whether our classifier can *derive
from a trace* a design decision Gemmini's authors made by hand — the same validation
pattern as when our finder's top candidate turned out to be an instruction CV32E40P
already implemented natively.

**In three weeks:** the classifier across all three tiers (cheap — it is analysis),
the fine and RoCC routes end-to-end on Rocket (both already done on CV32E40P/X), and
**one** Gemmini case with the tiled-versus-CISC A/B. We will not claim more.

## Expected Results

An analytical cycle model derived from the cores' manuals — not fitted — already lands
within **0.25%** of Verilator RTL across 14 points on two OpenHW cores, always
over-predicting (`gem5_align` reaches 3%/6.12% by tuning gem5 against BOOM). Four
discovered instructions were implemented in RTL; every measured saving fell **inside**
its predicted band, and two upstream `core-v-verif` bugs surfaced on the way. We expect
the most valuable results to be **failure modes a naive agentic loop would report as
wins**, both already measured: a correct CV-X-IF multiply-accumulate, top-ranked under
naive scoring, won **zero cycles**; a fusion won **zero** because removing instructions
removed the slack hiding a load-use hazard. Our screening node emits a *band*, and calibration measures how
often it held — that is the number we report.

**Three risks stated plainly.** (1) Our 0.25% came from a zero-wait-state memory
system; Rocket has caches and an MMU, and Gemmini's DMAs share a TLB, so we compose
the pipeline model with `gem5.py`/`champsim.py` rather than assume that figure
transfers. (2) Our known bound: recompiling relays out and reschedules code, so a
baseline trace cannot show the new schedule — hence bands, not point estimates. (3)
Gemmini's CISC unroller may already absorb most of the residual; if so, that is a
reportable negative result, measured by the same A/B.

**Deliverables:** a CHIA fork (BSD-3, upstreamable) adding a discovery node and a
granularity-aware screening node as a `chia/simulators/` entry alongside gem5 and
champsim, reusing `chia/chipyard`'s existing build, cosim and Verilator nodes;
`examples/mouna_loop/`; the Rocket pipeline model; and a 4-page paper reporting routing
accuracy, the fine/coarse interaction, and every predicted band against its measured
result. Per CHIA's AI-assisted contributions policy, agent involvement is disclosed and
authorship accountability is ours.

## Cost Estimate

**~$500** total: **$250** LLM API (Chisel generation and repair across ~10-15
candidates and three tiers), **$150** GCP CPU (Chipyard elaborate/Verilator builds,
Spike traces, benchmark runs), **$100** contingency for verification retries.
Discovery, screening and calibration run on Spike, Python and Verilator — cheap CPU
only, with no FPGA hours and no commercial EDA licences required.
