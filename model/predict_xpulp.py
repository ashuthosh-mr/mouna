#!/usr/bin/env python3
"""
Project the performance of Xpulp (CV32E40P's PULP ISA extension) from a
*baseline* Spike trace -- i.e. before the extension is enabled and before the
code is recompiled for it.

This is the same claim as the Zbb experiment on CV32E40X, but for a change Spike
cannot execute: Spike has no Xpulp support, so the Xpulp binary cannot simply be
traced. Instead the baseline trace is transformed analytically, applying the
three Xpulp features that the stall breakdown and candidate finder identified as
mattering, and the result is re-costed with the validated CV32E40P model.

Transformations applied (each measured on real RTL, see README):

  1. Hardware loops (`lp.setup`)
     A counted loop whose body contains no other control flow becomes a hardware
     loop: the loop-closing branch and its flush disappear entirely, and so does
     the induction-variable increment. The manual states hardware loops involve
     "zero stall cycles for jumping to the first instruction of a loop".
     Constraint honoured here: the CV32E40P hardware only supports two loop
     levels and requires HWLoop[1].end >= HWLoop[0].end + 8; GCC 7.1.1 violates
     that for nested loops, so by default only the innermost loop is converted
     (--nest to allow more).

  2. Post-increment load/store (`p.lw`/`p.sw rd, imm(rs1!)`)
     A pointer increment that feeds, or is fed by, a load/store on the same
     register folds into that memory instruction, removing the `addi`.

  3. Multiply-accumulate (`p.mac`)
     A `mul` whose product is consumed immediately by an `add` and then dies
     folds into one instruction. Measured at 1 cycle on RTL, exactly like `add`
     -- unlike the CV-X-IF equivalent, which cost 2 and won nothing.

Usage:
    ./predict_xpulp.py <baseline-spike-trace> [--actual-baseline N] [--actual-xpulp N]
"""

import argparse
import importlib.util
import os
from collections import Counter

_here = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_here, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


X = _load("cv32e40x_model", "cv32e40x_model.py")
P = _load("cv32e40p_model", "cv32e40p_model.py")


def is_ptr_bump(ins):
    """addi rX, rX, imm -- an in-place increment."""
    return (X.base_mnem(ins.mnem) == "addi"
            and ins.dest is not None
            and ins.dest in ins.srcs)


def mem_base_reg(ins):
    """Base register of a load/store, i.e. the rs1 inside `off(rs1)`."""
    ops = ins.ops
    if "(" not in ops or ")" not in ops:
        return None
    return (ops[ops.index("(") + 1: ops.index(")")].strip()) or None


def is_mem(ins):
    b = X.base_mnem(ins.mnem)
    return b in X.LOADS or b in X.STORES


def analyse_loop_body(body, use_hwloop=True):
    """Decide which instructions of one static loop body Xpulp removes.

    Returns (set_of_removable_pcs, Counter_of_reasons).

    The three effects modelled, in the order a compiler applies them:

      * hardware loop -- the loop-closing branch and the induction-variable
        increment are replaced by the hardware loop counter;
      * post-increment addressing -- once the pointer walks, the per-iteration
        address arithmetic (base re-materialisation + add of the induction
        variable) collapses into the load/store itself;
      * multiply-accumulate -- a `mul` whose product is consumed by the next
        `add` and then dies.

    The address-arithmetic case is the one that matters most and is not a
    peephole: it is induction-variable strength reduction, which the compiler
    only performs because post-increment addressing exists. Modelling the
    hardware alone under-predicts the benefit badly.
    """
    removable, why = set(), Counter()
    if not body:
        return removable, why

    br = body[-1]
    if X.base_mnem(br.mnem) not in X.BRANCHES:
        return removable, why

    # --- induction variable: incremented in-body and read by the loop branch
    # Identified even when hardware loops are disabled, because the
    # post-increment analysis below needs to know which register is the
    # induction variable.
    induction = None
    for ins in body:
        if is_ptr_bump(ins) and ins.dest in br.srcs:
            induction = ins.dest
            if use_hwloop:
                removable.add(ins.pc)
                why["hwloop_counter"] += 1
            break

    # --- hardware loop removes the branch itself (and its flush)
    if use_hwloop:
        removable.add(br.pc)
        why["hwloop_branch"] += 1

    # --- post-increment: address arithmetic feeding a memory op
    # Build defs within the body so an address chain can be walked backwards.
    defs = {}
    for idx, ins in enumerate(body):
        if ins.dest:
            defs.setdefault(ins.dest, []).append(idx)

    for idx, ins in enumerate(body):
        if not is_mem(ins):
            continue
        base = mem_base_reg(ins)
        if base is None:
            continue
        # Walk back the chain that produced this base register, within the body.
        chain, seen, work = [], set(), [base]
        while work:
            reg = work.pop()
            if reg in seen:
                continue
            seen.add(reg)
            for d in defs.get(reg, []):
                if d >= idx or body[d].pc in removable:
                    continue
                producer = body[d]
                m = X.base_mnem(producer.mnem)
                # only pure address arithmetic folds into post-increment
                if m in ("add", "addi", "mv", "c.mv", "slli", "sh1add",
                         "sh2add", "sh3add"):
                    chain.append(d)
                    work.extend(producer.srcs)
        # Fold the chain only if it actually depends on the induction variable
        # -- that is what makes it a walking pointer rather than a fixed address.
        if induction and any(induction in body[d].srcs for d in chain):
            for d in chain:
                if body[d].pc not in removable:
                    removable.add(body[d].pc)
                    why["post_increment_addr"] += 1

    # --- post-increment, pointer-walking form
    # `lw rd, 0(p)` together with `addi p, p, k` folds into `p.lw rd, k(p!)`.
    # This is the other shape post-increment takes: the index-chain case above
    # covers `base + i` recomputed each iteration, this one covers a pointer
    # that is already walking.
    mem_bases = {mem_base_reg(m) for m in body if is_mem(m)}
    mem_bases.discard(None)
    for ins in body:
        if ins.pc in removable or not is_ptr_bump(ins):
            continue
        if ins.dest in mem_bases:
            removable.add(ins.pc)
            why["post_increment_ptr"] += 1

    # --- multiply-accumulate
    for idx, ins in enumerate(body):
        if X.base_mnem(ins.mnem) != "mul" or ins.pc in removable:
            continue
        prod = ins.dest
        if prod is None:
            continue
        for j in range(idx + 1, min(idx + 4, len(body))):
            a = body[j]
            if X.base_mnem(a.mnem) == "add" and prod in a.srcs:
                dies = not any(prod in body[k].srcs
                               for k in range(j + 1, len(body)))
                if dies:
                    # Remove the `add` and keep the `mul` as the surviving
                    # instruction. p.mac reads rd, rs1 and rs2, so the fused
                    # instruction still depends on both multiplicands -- keeping
                    # the mul preserves that, and with it any load-use hazard on
                    # a just-loaded operand. Removing the mul instead would drop
                    # that dependency and under-predict by one cycle per
                    # iteration.
                    removable.add(a.pc)
                    why["mac_fusion"] += 1
                break

    return removable, why


def transform(region, allow_nested=False, use_hwloop=True, verbose=False):
    """Return (cycle_estimate, savings, surviving_count)."""
    n = len(region)

    # Identify static loop bodies from backward-taken branches.
    closers = {}
    for i, ins in enumerate(region):
        if X.base_mnem(ins.mnem) in X.BRANCHES and i + 1 < n:
            nxt = region[i + 1]
            if nxt.pc < ins.pc:
                closers.setdefault(ins.pc, nxt.pc)

    # Innermost first: a loop enclosing no other loop closer.
    def encloses(a_br, a_tgt, b_br, b_tgt):
        return a_tgt <= b_tgt and a_br >= b_br and (a_br, a_tgt) != (b_br, b_tgt)

    selected = []
    for br_pc, tgt in closers.items():
        inner = any(encloses(br_pc, tgt, o_br, o_tgt)
                    for o_br, o_tgt in closers.items())
        if not inner or allow_nested:
            selected.append((br_pc, tgt))

    # Reconstruct one static instance of each body from the trace.
    removable, why = set(), Counter()
    for br_pc, tgt in selected:
        body_by_pc = {}
        for ins in region:
            if tgt <= ins.pc <= br_pc:
                body_by_pc.setdefault(ins.pc, ins)
        body = [body_by_pc[pc] for pc in sorted(body_by_pc)]
        r, w = analyse_loop_body(body, use_hwloop=use_hwloop)
        removable |= r
        why += w

    survivors = [ins for ins in region if ins.pc not in removable]

    model = P.CV32E40PModel()
    total = 0
    for i, ins in enumerate(survivors):
        nxt = survivors[i + 1] if i + 1 < len(survivors) else None
        prev = survivors[i - 1] if i > 0 else None
        total += model.insn_cycles(ins, nxt) + model.hazard_penalty(prev, ins)

    return total, why, len(survivors), model


def _survivors_taken_branches(region):
    """Taken branches that survive conversion, i.e. those whose alignment
    penalty is uncertain after the code is relaid out."""
    out = []
    for i, ins in enumerate(region):
        if X.base_mnem(ins.mnem) in X.BRANCHES and i + 1 < len(region):
            nxt = region[i + 1]
            if nxt.pc != ins.fallthrough and (nxt.pc % 4) != 0:
                out.append(ins)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="BASELINE (non-Xpulp) spike trace")
    ap.add_argument("--marker", default="cycle")
    ap.add_argument("--nest", action="store_true",
                    help="also convert outer loops (CV32E40P supports 2 levels, but "
                         "GCC 7.1.1 mis-orders the loop registers -- see README)")
    ap.add_argument("--no-hwloop", action="store_true",
                    help="model Xpulp WITHOUT hardware loops (matches a -mnohwloop "
                         "build), i.e. post-increment addressing and p.mac only")
    ap.add_argument("--actual-baseline", type=int, default=None)
    ap.add_argument("--actual-xpulp", type=int, default=None)
    args = ap.parse_args()

    insns = X.parse_trace(args.trace)
    region, _, _ = X.slice_region(insns, args.marker)

    base_model = P.CV32E40PModel()
    base = 0
    for i, ins in enumerate(region):
        nxt = region[i + 1] if i + 1 < len(region) else None
        prev = region[i - 1] if i > 0 else None
        base += base_model.insn_cycles(ins, nxt) + base_model.hazard_penalty(prev, ins)

    new, saved, nsurv, _ = transform(region, allow_nested=args.nest,
                                     use_hwloop=not args.no_hwloop)

    print(f"Baseline : {len(region):>8} instrs  {base:>8} cycles (model)")
    if args.actual_baseline:
        print(f"           {'':>8}         {args.actual_baseline:>8} cycles (RTL)"
              f"   err {100.0*(base-args.actual_baseline)/args.actual_baseline:+.2f}%")

    print(f"\nXpulp transformations applied:")
    for k, v in sorted(saved.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v:>8}")
    print(f"  {'instrs removed':<20} {len(region)-nsurv:>8}")

    # Recompiling for the extension relays out the code, and on CV32E40P a
    # taken branch costs 3 or 4 cycles depending on whether its target is a
    # word-aligned/RVC instruction. The predictor works from the baseline
    # layout and cannot know the new one, so report that as an explicit band
    # rather than a single false-precision number.
    align_band = sum(1 for i, ins in enumerate(_survivors_taken_branches(region)))
    print(f"\nPredicted: {nsurv:>8} instrs  {new:>8} cycles")
    if align_band:
        print(f"           layout uncertainty +/-{align_band} cycles "
              f"({new-align_band}..{new}) -- recompilation changes branch-target "
              f"alignment, which this model cannot know in advance")
    print(f"Predicted speedup: {base/new:.3f}x  ({100.0*(base-new)/base:.1f}% fewer cycles)")

    if args.actual_xpulp:
        print(f"\nMeasured : {args.actual_xpulp:>8} cycles (RTL, Xpulp)")
        print(f"Measured speedup : {args.actual_baseline/args.actual_xpulp:.3f}x"
              if args.actual_baseline else "")
        err = (new - args.actual_xpulp) / args.actual_xpulp * 100.0
        print(f"Prediction error : {err:+.2f}%")


if __name__ == "__main__":
    main()
