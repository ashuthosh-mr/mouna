#!/usr/bin/env python3
"""
CV32E40P cycle-count model driven by a Spike instruction trace.

Same approach as cv32e40x_model.py -- trace in, cycles out, timings taken from
the core's own user manual ("Pipeline Details") rather than guessed -- but for
CV32E40P, which is a different microarchitecture despite also being a 4-stage
in-order pipeline.

Everything except the timing table is shared with the CV32E40X model, so this
file *is* the specification of how the two cores differ:

    instruction / event      CV32E40X            CV32E40P
    ---------------------    ----------------    ----------------------------
    mulh, mulhsu, mulhu      4                   5
    fence, fence.i           5                   2
    CSR access               1 (4 for jvt)       4 for mstatus/mepc/mtvec/
                                                 mcause/mcycle/minstret/
                                                 mhpmcounter*/mcountinhibit/
                                                 mhpmevent*/debug CSRs,
                                                 1 for everything else
    jalr data hazard         +1, or +2 if the    +1 after any immediately
                             producer is a load  preceding producer
    other CSR hazards        several documented  not documented for this core

Identical on both: integer ops (1), aligned load/store (1), mul (1), div/rem
(3 + leading zeros of the divisor), jump (2), branch not-taken (1), branch
taken (3), and the +1 penalty when a control-flow target is a non-word-aligned
non-RVC instruction.

Usage:
    ./cv32e40p_model.py <spike-trace> [--actual N]
"""

import argparse
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "cv32e40x_model", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "cv32e40x_model.py"))
X = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(X)

# Re-export the shared trace machinery so this module can be used standalone.
parse_trace = X.parse_trace
slice_region = X.slice_region
base_mnem = X.base_mnem
clz32 = X.clz32

# CSRs the CV32E40P manual lists as costing 4 cycles to access. Matched against
# the CSR name Spike prints in the disassembly, so `rdcycle` (which reads
# `cycle`) and explicit `csrr x, mcycle` are both covered.
SLOW_CSRS = {
    "mstatus", "mepc", "mtvec", "mcause",
    "mcycle", "minstret", "mcycleh", "minstreth",
    "mcountinhibit", "cycle", "instret", "cycleh", "instreth",
    "dcsr", "dscr", "dpc", "dscratch0", "dscratch1", "privlv",
}


def _is_slow_csr(ops):
    o = ops.lower()
    if "mhpmcounter" in o or "mhpmevent" in o:
        return True
    return any(c in o.split() or c in o.replace(",", " ").split()
               for c in SLOW_CSRS)


class CV32E40PModel(X.CV32E40XModel):
    """CV32E40P timings. Only the documented differences are overridden."""

    def insn_cycles(self, ins, nxt):
        b = base_mnem(ins.mnem)

        if b in X.FENCES:
            # 2 cycles on CV32E40P (5 on CV32E40X): implemented as a jump to the
            # following instruction, so it costs a jump rather than a full flush.
            self.notes["fence"] += 1
            pen = self.target_penalty(nxt)
            self.stalls["fence"] += 1
            self.stalls["target_misalign"] += pen
            return 2 + pen

        if b in X.CSR_INSNS:
            self.notes["csr"] += 1
            if _is_slow_csr(ins.ops):
                self.notes["csr_slow"] += 1
                self.stalls["csr_slow"] += 3
                return 4
            return 1

        if b in X.MUL_HIGH:
            # 5 cycles on CV32E40P, 4 on CV32E40X.
            self.notes["mulh"] += 1
            self.stalls["mul_multicycle"] += 4
            return 5

        # Everything else matches CV32E40X.
        return super().insn_cycles(ins, nxt)

    def hazard_penalty(self, prev, ins):
        """CV32E40P documents exactly two 1-cycle hazards: a load-use hazard,
        and a jalr depending on any immediately preceding instruction. Note the
        jalr case is +1 regardless of whether the producer was a load, unlike
        CV32E40X where a preceding load costs +2."""
        if prev is None or prev.dest is None or prev.dest == "zero":
            return 0
        if prev.dest not in ins.srcs:
            return 0

        if base_mnem(ins.mnem) in X.JALR_LIKE:
            self.notes["hazard_jalr"] += 1
            self.stalls["raw_jalr"] += 1
            return 1
        if base_mnem(prev.mnem) in X.LOADS:
            self.notes["hazard_load_use"] += 1
            self.stalls["raw_load_use"] += 1
            return 1
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--marker", default="cycle")
    ap.add_argument("--whole", action="store_true")
    ap.add_argument("--div-cycles", type=int, default=35)
    ap.add_argument("--actual", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    insns = parse_trace(args.trace)
    if not insns:
        raise SystemExit(f"no instructions parsed from {args.trace}")

    if args.whole:
        region = insns
        print(f"Modelling entire trace: {len(region)} instructions")
    else:
        region, i0, i1 = slice_region(insns, args.marker)
        print(f"Measured region: trace instrs {i0 + 1}..{i1 - 1} "
              f"({len(region)} instructions)")

    model = CV32E40PModel(div_cycles=args.div_cycles, verbose=args.verbose)
    cycles = model.run(region)

    n = len(region)
    print(f"\nInstructions : {n}")
    print(f"Model cycles : {cycles}")
    if n:
        print(f"Model CPI    : {cycles / n:.3f}")

    stall_total = sum(model.stalls.values())
    print("\nCycle breakdown (cycles = compute + stalls):")
    print(f"  {'compute (1/instr)':<22} {n:>10}  {100.0*n/cycles:5.1f}%")
    for k, v in sorted(model.stalls.items(), key=lambda kv: -kv[1]):
        if v:
            print(f"  {'stall: ' + k:<22} {v:>10}  {100.0*v/cycles:5.1f}%")
    print(f"  {'-- total stalls':<22} {stall_total:>10}  {100.0*stall_total/cycles:5.1f}%")
    print(f"\n  achieved IPC          {n/cycles:.3f}   "
          f"(headroom to IPC=1: {100.0*stall_total/cycles:.1f}% of cycles)")

    print("\nInstruction mix / events:")
    for k, v in sorted(model.notes.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v}")

    n_div = model.notes.get("div_rem", 0)
    n_exact = model.notes.get("div_rem_exact", 0)
    if n_div and n_exact < n_div:
        print(f"\nNOTE: {n_div - n_exact} of {n_div} div/rem had no recoverable "
              f"divisor and were charged the worst case ({args.div_cycles} cycles). "
              f"Re-run spike with --log-commits.")
    elif n_exact:
        print(f"\n{n_exact} div/rem costed exactly from recovered divisors.")

    if args.actual is not None:
        err = (cycles - args.actual) / args.actual * 100.0
        print(f"\nRTL cycles   : {args.actual}")
        print(f"Model cycles : {cycles}")
        print(f"Error        : {err:+.2f}%")


if __name__ == "__main__":
    main()
