#!/usr/bin/env python3
"""
Custom-instruction candidate finder for CV32E40X / CV-X-IF.

Mines a Spike trace for straight-line instruction sequences that execute often
enough to be worth fusing into a single custom instruction, and scores each
candidate with the same cycle model used for validation -- so the estimated
saving is on the same footing as the validated cycle counts.

Fusability constraints reflect what CV-X-IF can actually accept:
  * no control flow inside the sequence (a fused op is one instruction)
  * bounded number of distinct source registers read from the register file
    (CV-X-IF X_NUM_RS, typically 2 or 3)
  * exactly one destination register written (X_RFW_WIDTH = 32, single write)
  * by default no loads/stores, since offloading memory needs the optional
    xif_mem interface; pass --allow-mem to include them

Usage:
    ./find_candidates.py <spike-trace> [--max-len N] [--num-rs N] [--top N]
"""

import argparse
import importlib.util
import os
from collections import Counter, defaultdict

_here = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_here, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = _load("cv32e40x_model", "cv32e40x_model.py")
_P = _load("cv32e40p_model", "cv32e40p_model.py")


def is_control(ins):
    b = M.base_mnem(ins.mnem)
    return b in M.BRANCHES or b in M.JUMPS


def is_mem(ins):
    b = M.base_mnem(ins.mnem)
    return b in M.LOADS or b in M.STORES


def seq_signature(seq):
    """Canonical shape of a sequence: mnemonics plus the dataflow pattern.

    Registers are renamed to positional slots so that the same computation with
    different register allocation collapses to one candidate.
    """
    slot = {}
    def name(r):
        if r not in slot:
            slot[r] = f"r{len(slot)}"
        return slot[r]
    parts = []
    for ins in seq:
        srcs = ",".join(name(s) for s in ins.srcs)
        dst = name(ins.dest) if ins.dest else "-"
        parts.append(f"{M.base_mnem(ins.mnem)} {dst}<-{srcs}")
    return " ; ".join(parts)


def analyse(seq, region, end, lookahead=32):
    """Return (external_srcs, live_out) for a candidate sequence.

    external_srcs are registers the fused instruction must read from the
    register file (values produced *and* consumed inside the sequence become
    internal wires and cost nothing).

    live_out is determined by scanning forward from the end of the sequence: a
    register written inside is live-out only if something reads it before it is
    overwritten. Without this, an intermediate such as the product inside a
    multiply-accumulate looks like a second result and the candidate is
    wrongly rejected.
    """
    produced, external = set(), []
    for ins in seq:
        for s in ins.srcs:
            if s not in produced and s not in external and s != "zero":
                external.append(s)
        if ins.dest:
            produced.add(ins.dest)

    live = set()
    pending = set(produced)
    for k in range(end, min(end + lookahead, len(region))):
        if not pending:
            break
        nxt = region[k]
        for s in nxt.srcs:
            if s in pending:
                live.add(s)
                pending.discard(s)
        if nxt.dest in pending:      # overwritten before use -> dead
            pending.discard(nxt.dest)
    live |= pending  # still unresolved at the horizon: assume live
    return external, sorted(live)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--max-len", type=int, default=4,
                    help="longest sequence to consider (default 4)")
    ap.add_argument("--num-rs", type=int, default=3,
                    help="max register-file source operands, i.e. CV-X-IF X_NUM_RS (default 3)")
    ap.add_argument("--allow-mem", action="store_true",
                    help="allow loads/stores inside a candidate (needs xif_mem)")
    ap.add_argument("--core", choices=("40x", "40p"), default="40x",
                    help="which core's timing model to score with (default 40x)")
    ap.add_argument("--native", action="store_true",
                    help="the instruction is added by a decoder edit rather than "
                         "offloaded over CV-X-IF, so it retires in 1 cycle with no "
                         "interface round-trip. Measured on CV32E40P: pg.add3 and "
                         "p.mac both cost exactly 1 cycle, same as add. Implies "
                         "--offload-latency 1.")
    ap.add_argument("--offload-latency", type=int, default=2,
                    help="cycles a CV-X-IF offloaded instruction takes to retire. "
                         "Measured at 2 on CV32E40X (rtl/pg_xif_mac.sv): the result "
                         "must be registered and handed back over result_valid/ready, "
                         "so a fused op is NOT free. Scoring fusions at 1 cycle "
                         "over-values them and makes 2-instruction fusions look "
                         "profitable when they are break-even.")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--marker", default="cycle")
    args = ap.parse_args()

    if args.native:
        args.offload_latency = 1

    insns = M.parse_trace(args.trace)
    region, _, _ = M.slice_region(insns, args.marker)

    # Cost each instruction in isolation so a candidate's saving can be scored
    # with the validated model rather than guessed.
    model = _P.CV32E40PModel() if args.core == "40p" else M.CV32E40XModel()
    cost = []
    for i, ins in enumerate(region):
        nxt = region[i + 1] if i + 1 < len(region) else None
        prev = region[i - 1] if i > 0 else None
        cost.append(model.insn_cycles(ins, nxt) + model.hazard_penalty(prev, ins))
    total_cycles = sum(cost)

    # Enumerate straight-line windows.
    cand_count = Counter()
    cand_cycles = Counter()
    cand_example = {}
    n = len(region)
    for i in range(n):
        for L in range(2, args.max_len + 1):
            if i + L > n:
                break
            seq = region[i:i + L]
            if any(is_control(x) for x in seq):
                break
            if not args.allow_mem and any(is_mem(x) for x in seq):
                break
            ext, live = analyse(seq, region, i + L)
            if len(ext) > args.num_rs or len(live) > 1:
                continue
            sig = seq_signature(seq)
            cand_count[sig] += 1
            cand_cycles[sig] += sum(cost[i:i + L])
            cand_example.setdefault(sig, (len(seq), len(ext), len(live)))

    print(f"Region: {n} instructions, {total_cycles} cycles "
          f"(model), constraints: max_len={args.max_len} "
          f"X_NUM_RS<={args.num_rs} mem={'yes' if args.allow_mem else 'no'} "
          f"offload_latency={args.offload_latency}\n")

    rows = []
    for sig, cnt in cand_count.items():
        ln, nsrc, ndst = cand_example[sig]
        cyc = cand_cycles[sig]
        # Replacing the sequence with one custom instruction that itself costs
        # offload_latency cycles to retire.
        saved = cyc - cnt * args.offload_latency
        if saved <= 0:
            continue        # offload costs more than the sequence it replaces
        rows.append((saved, cnt, ln, nsrc, cyc, sig))
    rows.sort(reverse=True)

    print(f"{'saved':>8} {'%tot':>6} {'execs':>7} {'len':>4} {'srcs':>5}  pattern")
    for saved, cnt, ln, nsrc, cyc, sig in rows[:args.top]:
        print(f"{saved:>8} {100.0*saved/total_cycles:>5.1f}% {cnt:>7} {ln:>4} "
              f"{nsrc:>5}  {sig}")

    if not rows:
        print("  (no candidates met the constraints)")


if __name__ == "__main__":
    main()
