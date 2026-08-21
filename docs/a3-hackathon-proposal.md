# Screen Before You Build: Trace-Driven Custom-Instruction Discovery as a CHIA Loop

**Track:** domain-specific architecture co-design / microarchitecture analysis
**Target core:** CVA6 (6-stage in-order; already a Chipyard tile, and already
reachable in CHIA as ESP's `ariane` CPU tile)

## The gap

`examples/riscv_extensions` (CS2) is an impressive loop: an agent implements
Bitmanip, Crypto and Zicond in RTL, verified by `riscv_dv_gen_node` and
`cosim_node`'s Spike/Verilator lockstep, then measured at scale. Two questions it
does not ask:

1. **Which instruction should exist?** Those three are *published specs*. The agent
   implements a known answer; nothing derives a candidate from an application.
2. **Is it worth building, before it is built?** The answer arrives only after RTL
   exists and a long simulation has run.

CS4 names the consequence: cheap feedback is low-fidelity and invites reward
hacking, high-fidelity cascades are expensive. And the repo shows exactly where the
hole is — `chia/simulators/` contains `gem5.py` and `champsim.py`, and nothing
cheaper or more accurate; no example mines a trace for candidate instructions.

We propose the missing front end: **a candidate-discovery node and a
high-accuracy analytical screening node**, so RTL generation is only ever spent on
candidates that have already been shown to pay.

## The loop

Composed almost entirely from nodes CHIA already has:

| stage | node | new? |
|---|---|---|
| 1. build target app | `riscv_build_node` | existing |
| 2. instruction trace | Spike (`-l --log-commits`) | thin new node |
| 3. **candidate discovery** | mine fusable straight-line sequences under encoding constraints | **new** |
| 4. **analytical screening** | manual-derived CVA6 pipeline model; emits a *band*, not a point | **new** |
| 5. write RTL + decoder for top survivor | `ClaudeCodeLLM` + `BashTool`, as CS2 | existing |
| 6. verify | `riscv_dv_gen_node` + `cosim_node` (Spike/Verilator lockstep) | existing |
| 7. measure | `ChiselBuildNode` + `verilator_run_node` | existing |
| 8. calibrate | record predicted band vs measured, feed back | **new** |

Stages 2-4 and 8 are programmatic and cost cents. Only stage 5 spends API credits,
and only on survivors. Stage 8 is the scientific payload: the loop's output is not a
speedup number but a **calibration record** — for every candidate, what was
predicted and what was measured.

## Why this is credible

We have run this end to end outside CHIA, on two OpenHW in-order cores (CV32E40P,
CV32E40X); the artifact is open source:

- An analytical cycle model derived from the cores' manuals — not fitted — within
  **0.25%** of Verilator RTL across 14 points (7 Embench kernels x 2 cores), and
  always an over-prediction. For comparison, CHIA's `gem5_align` case study reaches
  3% / 6.12% by having an agent tune gem5 against BOOM.
- **Four discovered custom instructions** implemented in RTL and measured. Every
  measured saving landed **inside** its predicted band.
- Two bugs found in upstream `core-v-verif` while getting there, one of which made
  every store and load silently return zero.

## The results we expect to report, including the negative ones

Headline metrics are screening accuracy on CVA6 and RTL-generation attempts avoided.
But the findings we think matter most to A3 are the **failure modes that a naive
agentic loop reports as wins** — both already measured on real RTL:

- **Interface cost erases short fusions.** A CV-X-IF multiply-accumulate — correct,
  and the top-ranked candidate under naive scoring — measured **exactly zero**
  speedup: the offload round-trip costs the cycle the fusion saved.
- **Fusion can cancel itself.** Removing instructions removes scheduling slack. One
  instruction we added won **zero cycles**: the shorter loop let the compiler place a
  load directly into the fused operand, and the new load-use stall exactly offset the
  instruction removed.

Neither is visible to a scorer that costs candidates in isolation, and both are
precisely the shape of result an agent would confidently claim as a success. Our
screening node reports a band rather than a point estimate specifically to surface
them, and stage 8 measures how often the band was right.

## Honest risk

The 0.25% figure came from in-order pipelines with a **zero-wait-state memory
system**. CVA6 has L1 caches, an MMU, and a scoreboard permitting out-of-order
writeback for long-latency ops. We do not expect that number to transfer and will
not claim it does. The plan is to model the CVA6 pipeline analytically and compose it
with an existing memory-system evaluator (`gem5.py` or `champsim.py`) rather than
pretend one analytical model covers both — which is itself the heterogeneous-evaluator
composition CHIA is built for. If pipeline-only accuracy turns out to be insufficient
for screening, that is a reportable result about where analytical screening stops
working, not a failed loop.

## Cost estimate

| item | estimate |
|---|---|
| LLM API — RTL generation and repair across ~10-15 candidates | $200 |
| GCP CPU — Chipyard/Verilator builds, Spike traces, Embench runs | $100 |
| Contingency — verification retries, extra candidates | $100 |
| **Total** | **~$400** |

Stages 2-4 and 8 are Spike, Python and Verilator: cheap CPU only. No FPGA hours are
needed for the screening claim; one optional FireSim run would strengthen the final
measurement if credits allow.

## Deliverables

An open-sourced CHIA loop; the discovery and screening nodes written to be reusable
independently of our core choice (a new `chia/simulators/` entry alongside gem5 and
champsim); the CVA6 pipeline model; and a 4-page paper reporting screening accuracy,
compute avoided, and the full calibration record of predicted bands versus measured
results.
