# Granularity-Aware Co-Design: Deciding *What Kind* of Hardware to Build, Before Building It

**Target:** CVA6 (in-order RV64), verified on its own upstream Verilator/Spike
testbench — not Chipyard's CVA6 tile, which requires VCS
**Prior work:** open-source, already running end-to-end outside CHIA on two OpenHW cores

## Overview

CHIA has both ends of the granularity spectrum. `examples/riscv_extensions` has an
agent implement a RISC-V extension in RTL, verified by `riscv_dv_gen_node` and
`cosim_node`'s Spike/Verilator lockstep. `examples/esp_accel_loop` has an agent
implement a DMA-driven ESP accelerator tile in HLS C++, validated in full-SoC
simulation. **Neither chooses.** CS2 is handed a published spec (Bitmanip, Crypto,
Zicond); the ESP loop is handed "implement memcpy." Nothing derives a candidate from
an application, and nothing decides *at what granularity* work should be accelerated.
No cheap stage exists that could: `chia/simulators/` holds only gem5 and champsim, and
Spike appears only as lockstep verification, never as a trace source for analysis. We
propose the missing decision stage: **one trace, one model, three routes** — native
decoder edit, CV-X-IF coprocessor, or ESP accelerator tile — chosen by measured
break-even cost, not intuition.

## Methodology

```
app ─▶ spike -l ─▶ discover hot regions & fusable sequences ─▶ classify by granularity
                                        │
      ┌─────────────────────────────────┼─────────────────────────────────┐
      ▼                                 ▼                                 ▼
 1-2 instr, ALU                  3+ instr, ALU/mem                 loop nest / kernel
 native decoder edit             CV-X-IF coprocessor               ESP accelerator tile
 measured cost: 1 cyc            measured cost: 2 cyc              DMA + config + sync
      │                                 │                                 │
      └──── agent writes RTL / HLS (riscv_extensions, esp_accel_loop) ────┘
                                        │
       verify (Spike/Verilator lockstep, riscv-dv) ─▶ measure (RTL cycles) ─▶ calibrate
```

Thresholds come from our RTL measurements, not intuition: an in-pipeline custom
instruction retires in **1** cycle, a CV-X-IF offload costs **2** — so a
two-instruction fusion is break-even by construction, and we measured one at
**exactly zero speedup**. Coarse offload pays only above DMA, configuration and
synchronisation cost. The interaction is the real contribution: for a coarse
accelerator, speedup is set by the *residual* core cost — marshalling data into and
out of the accelerator — not accelerator throughput. That residual is exactly what
our stall breakdown already measures, so offloading a kernel *creates* the
marshalling loop that then wants a post-increment or indexed-load instruction — one
trace and one model answer both the "offload or not" and "fuse or not" questions, and
report how they interact. Neither existing CHIA case study can express that.

**In three weeks:** the classifier across all three tiers (cheap — it is analysis),
the native and CV-X-IF routes end-to-end on CVA6 (both already done on CV32E40P/X),
and **one** coarse-grained case, predicted through `esp_accel_loop`'s model. **Stretch
goal, not committed:** a hand-built, fully open-source AXI/DMA accelerator in CVA6's
own testbench, giving the coarse tier a measured result too. We will not claim more.

## Expected Results

An analytical cycle model derived from the cores' manuals — not fitted — already lands
within **0.25%** of Verilator RTL across 14 points on two OpenHW cores, always
over-predicting (`gem5_align` reaches 3%/6.12% by tuning gem5 against BOOM). Four
discovered instructions were implemented in RTL; every measured saving fell **inside**
its predicted band. Two upstream `core-v-verif` bugs surfaced on the way, one making
every load and store silently return zero. We expect the most valuable results on
CVA6 to be **failure modes a naive agentic loop would report as wins**, both already
seen on the smaller cores: a correct CV-X-IF multiply-accumulate, top-ranked under
naive scoring, won **zero cycles**; a fusion won **zero** because removing
instructions removed the slack hiding a load-use hazard. Our screening node emits a
*band*, and calibration measures how often it held — that is the number we report.

**Two risks stated plainly.** Our 0.25% came from a zero-wait-state memory system;
CVA6 has caches, an MMU and out-of-order writeback, so we will compose the pipeline
model with `gem5.py`/`champsim.py` for the memory system rather than assume it
transfers. `esp_accel_loop` validates via Xcelium; without commercial EDA access the
coarse route is reported predicted-only, with the two RISC-V routes carrying measured
RTL results.

**Deliverables:** a CHIA fork (BSD-3, upstreamable) adding a discovery node and a
granularity-aware screening node as a `chia/simulators/` entry alongside gem5 and
champsim; `examples/mouna_loop/`; the CVA6 pipeline model; and a 4-page paper
reporting routing accuracy, compute avoided, the fine/coarse interaction, and the
full record of predicted bands versus measured results. Per CHIA's AI-assisted
contributions policy, agent involvement is disclosed and authorship accountability is
ours.

## Cost Estimate

**~$500** total: **$250** LLM API (RTL/HLS generation and repair across ~10-15
candidates and three tiers), **$150** GCP CPU (Chipyard/Verilator builds, Spike
traces, benchmark runs), **$100** contingency for verification retries. Discovery,
screening and calibration run on Spike, Python and Verilator — cheap CPU only, no FPGA
hours needed for the routing claim.
