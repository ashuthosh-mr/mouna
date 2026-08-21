# Screen Before You Build: Trace-Driven Custom-Instruction Discovery as a Low-Cost CHIA Loop

**Track:** domain-specific architecture co-design / microarchitecture analysis
**Target core:** CVA6 (6-stage in-order, already integrated as a Chipyard tile)

## The gap we want to close

CHIA's CS2 shows an agent can implement a *given* ISA extension (Bitmanip, Crypto,
Zicond) in RTL and measure it credibly. Two questions it does not ask:

1. **Which instruction should exist?** The extensions in CS2 are published specs. The
   agent implements a known answer; it does not derive one from an application.
2. **Is it worth building, before you build it?** CS2 learns the answer by executing
   25 trillion instructions on FireSim. That is a definitive measurement and an
   expensive one — and it arrives only after the RTL exists.

CS4 names the resulting problem directly: cheap feedback stages are low-fidelity and
invite reward hacking, while high-fidelity cascades are costly. CHIA's cheap stage is
gem5, LLM-aligned to **3% / 6.12%** error against BOOM RTL.

We propose the missing front end: a **high-accuracy, near-zero-cost screening node**
that decides which candidate instructions deserve RTL at all.

## The loop

```
  app binary ──▶ [1] spike -l trace
                      │
                      ▼
                 [2] candidate discovery      mine straight-line fusable sequences
                      │                       under real ISA encoding constraints
                      ▼                       (<=N register sources, 1 live-out,
                 [3] analytical screening      no internal control flow)
                      │                       cost each with a manual-derived CVA6
                      │                       pipeline model; emit a BAND, not a
                      │                       point estimate
                      ▼
                 [4] agent: write RTL + decoder for the top survivor   ◀── LLM node
                      │
                      ▼
                 [5] verify: Spike co-sim + riscv-dv random mixes
                      │
                      ▼
                 [6] measure: Verilator; compare against the predicted band
```

Nodes 2, 3 and 6 are programmatic and cheap; only node 4 spends API credits, and only
on candidates that survived screening. The loop's output is not just a speedup number
but a **calibration record**: for every candidate, predicted band vs measured result.

## Why we can claim this will work

We have already run this end to end, outside CHIA, on two OpenHW in-order cores
(CV32E40P and CV32E40X), and the artifact is open source:

- **Cycle model within 0.25%** of Verilator RTL across 14 points (7 Embench kernels x 2
  cores), derived from the cores' manuals rather than fitted, always an over-prediction.
- **Four discovered custom instructions** implemented in RTL and measured. Every
  measured saving landed **inside** its predicted band.
- The screening stage's value is mostly in what it *rejects*: on one kernel it pruned
  33 candidates to 11 once a measured interface cost was fed back.

## The results we expect to report — including the negative ones

The headline deliverable is screening accuracy on CVA6 and the compute avoided. But
the findings we think matter most to A3 are the **failure modes a naive agentic loop
reports as wins**, both of which we have already measured on real RTL:

- **Interface cost erases short fusions.** A CV-X-IF multiply-accumulate coprocessor —
  correct, and the top-ranked candidate under naive scoring — measured **exactly zero
  speedup**, because the offload round-trip costs the cycle the fusion saved.
- **Fusion can expose a hidden hazard and cancel itself.** Removing instructions
  removes scheduling slack. One instruction we added won **0 cycles**: the shorter loop
  let the compiler place a load directly into the fused operand, and the new load-use
  stall exactly cancelled the instruction removed.

Both are precisely the reward-hacking-shaped errors CS4 warns about, and neither is
visible to a loop that scores candidates in isolation. Our screening node reports a
band rather than a point estimate specifically to surface them.

## Honest risk, and how we handle it

Our 0.25% figure was obtained on in-order pipelines with a zero-wait-state memory
system. **CVA6 has L1 caches, an MMU, and a scoreboard that permits out-of-order
writeback for long-latency operations.** We do not expect that number to transfer, and
we will not claim it does. The plan is to model the CVA6 pipeline analytically and
compose it with a separate memory-system evaluator (gem5 or ChampSim, already CHIA
nodes) rather than pretend one analytical model covers both — which is itself an
exercise in the heterogeneous-evaluator composition CHIA is built for. If pipeline-only
accuracy proves insufficient for screening, that is a reportable result, not a failure
of the loop.

## Cost estimate

Deliberately at the low end of the band. Nodes 1-3 and 6 are Spike, Python and
Verilator — cheap CPU only. Credits are spent almost entirely on node 4 (the RTL-writing
agent) and its verification retries.

| item | estimate |
|---|---|
| Gemini API — RTL generation + repair across ~10-15 candidate instructions | $200 |
| GCP CPU — Chipyard/Verilator builds and Embench/SPEC-subset runs | $100 |
| Contingency — verification retries, extra candidates | $100 |
| **Total** | **~$400** |

No FPGA hours are required for the screening claim. A single optional FireSim run at
the end would strengthen the final measurement, if credits allow.

## Deliverables

An open-sourced CHIA loop with the discovery and screening nodes reusable
independently of our core choice, the CVA6 pipeline model, and a 4-page paper reporting
screening accuracy, compute avoided, and the calibration record of predicted bands vs
measured results.
