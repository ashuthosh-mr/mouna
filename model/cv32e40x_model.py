#!/usr/bin/env python3
"""
CV32E40X cycle-count model driven by a Spike instruction trace.

Timing comes from the CV32E40X user manual ("Pipeline Details" chapter), which
specifies exact cycle counts per instruction type and the hazard penalties for
this 4-stage in-order pipeline. The manual's counts assume zero stall on the
instruction- and data-side memory interfaces; the core-v-verif `core` testbench
satisfies that under Verilator, because its random-stall configuration block is
compiled out (`ifndef VERILATOR`) and all stall registers are zeroed.

Usage:
    ./cv32e40x_model.py <spike-trace> [--region-marker cycle]

By default the model measures the region between the first and second CSR reads
of `cycle` (i.e. the two rdcycle instructions bracketing a kernel), matching how
the benchmarks time themselves in hardware.
"""

import argparse
import re
import sys
from collections import Counter

# --------------------------------------------------------------------------
# Trace parsing
# --------------------------------------------------------------------------

# e.g. "core   0: 0x8000005c (0xc0002373) csrr    t1, cycle"
TRACE_RE = re.compile(
    r"core\s+\d+:\s+0x([0-9a-fA-F]+)\s+\(0x([0-9a-fA-F]+)\)\s+(\S+)\s*(.*)"
)

REG_RE = re.compile(r"\b(x\d+|zero|ra|sp|gp|tp|t[0-6]|s[0-9]|s1[01]|a[0-7]|fp)\b")


class Insn:
    __slots__ = ("pc", "enc", "size", "mnem", "ops", "dest", "srcs")

    def __init__(self, pc, enc, enc_str, mnem, ops):
        self.pc = pc
        self.enc = enc
        # Spike prints RVC instructions as 4 hex digits, 32-bit as 8.
        self.size = 2 if len(enc_str) <= 4 else 4
        self.mnem = mnem
        self.ops = ops
        self.dest, self.srcs = decode_regs(mnem, ops)

    @property
    def fallthrough(self):
        return self.pc + self.size

    def __repr__(self):
        return f"0x{self.pc:08x} {self.mnem} {self.ops}"


def base_mnem(m):
    """Strip the RVC 'c.' prefix so one table covers both forms."""
    return m[2:] if m.startswith("c.") else m


LOADS = {"lw", "lh", "lhu", "lb", "lbu", "lwu", "flw", "fld", "lwsp", "ldsp"}
STORES = {"sw", "sh", "sb", "swsp", "sdsp", "fsw", "fsd"}
BRANCHES = {"beq", "bne", "blt", "bge", "bltu", "bgeu", "beqz", "bnez",
            "blez", "bgez", "bltz", "bgtz", "bgt", "ble", "bgtu", "bleu"}
JUMPS = {"jal", "j", "jr", "jalr", "ret", "tail", "call", "mret", "sret", "uret"}
JALR_LIKE = {"jalr", "jr", "ret", "call", "tail"}
MUL_HIGH = {"mulh", "mulhsu", "mulhu"}
DIV_REM = {"div", "divu", "rem", "remu"}
CSR_INSNS = {"csrr", "csrw", "csrs", "csrc", "csrrw", "csrrs", "csrrc",
             "csrrwi", "csrrsi", "csrrci", "csrwi", "csrsi", "csrci"}
FENCES = {"fence", "fence.i", "fencei"}
# Instructions whose first operand is a destination register.
NO_DEST = BRANCHES | STORES | {"j", "jr", "ret", "fence", "fence.i", "nop",
                               "mret", "sret", "uret", "ecall", "ebreak",
                               "csrw", "csrs", "csrc", "csrwi", "csrsi", "csrci"}


def decode_regs(mnem, ops):
    """Return (dest_reg, [src_regs]) parsed from the disassembly text.

    This is deliberately textual: it only needs to be good enough to spot the
    RAW dependencies the manual's hazard rules care about (load-use and jalr).
    """
    b = base_mnem(mnem)
    regs = REG_RE.findall(ops)
    if not regs:
        return None, []

    if b in NO_DEST:
        return None, regs
    # Everything else writes its first operand and reads the remainder.
    return regs[0], regs[1:]


def parse_trace(path):
    insns = []
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = TRACE_RE.match(line)
            if not m:
                continue  # exception lines, register dumps, etc.
            pc_s, enc_s, mnem, ops = m.groups()
            insns.append(Insn(int(pc_s, 16), int(enc_s, 16), enc_s, mnem, ops.strip()))
    return insns


# --------------------------------------------------------------------------
# Timing model
# --------------------------------------------------------------------------

class CV32E40XModel:
    """Cycle model per the CV32E40X user manual, Pipeline Details chapter."""

    def __init__(self, div_cycles=35, verbose=False):
        # Division/remainder take 3..35 cycles depending on the number of
        # leading zeros in operand b. `spike -l` does not print operand values,
        # so this is a parameter; the default is the worst case. The model
        # reports whether any div/rem appeared in the measured region so this
        # assumption is never silently load-bearing.
        self.div_cycles = div_cycles
        self.verbose = verbose
        self.notes = Counter()

    def target_penalty(self, nxt):
        """+1 cycle when a control-flow target is a non-word-aligned,
        non-RVC (32-bit) instruction."""
        if nxt is None:
            return 0
        if (nxt.pc % 4) != 0 and nxt.size == 4:
            return 1
        return 0

    def insn_cycles(self, ins, nxt):
        b = base_mnem(ins.mnem)

        if b in FENCES:
            self.notes["fence"] += 1
            return 5 + self.target_penalty(nxt)

        if b in CSR_INSNS:
            self.notes["csr"] += 1
            return 1  # 4 only for jvt, which we do not use

        if b in DIV_REM:
            self.notes["div_rem"] += 1
            return self.div_cycles

        if b in MUL_HIGH:
            self.notes["mulh"] += 1
            return 4

        if b == "mul":
            self.notes["mul"] += 1
            return 1

        if b in LOADS or b in STORES:
            # 1 cycle for aligned accesses. Misaligned word transfers and
            # halfword transfers crossing a word boundary cost 2, but `spike -l`
            # does not print effective addresses, so aligned is assumed.
            self.notes["load" if b in LOADS else "store"] += 1
            return 1

        if b in BRANCHES:
            taken = nxt is not None and nxt.pc != ins.fallthrough
            if taken:
                self.notes["branch_taken"] += 1
                return 3 + self.target_penalty(nxt)
            self.notes["branch_not_taken"] += 1
            return 1

        if b in JUMPS:
            self.notes["jump"] += 1
            return 2 + self.target_penalty(nxt)

        self.notes["alu"] += 1
        return 1  # integer computational, Zba/Zbb/Zbc/Zbs, Zca/Zcb

    def hazard_penalty(self, prev, ins):
        """Manual: 1-cycle penalty for a load-use hazard and for a jalr
        depending on an immediately preceding non-load; 2 cycles for a jalr
        depending on an immediately preceding load."""
        if prev is None or prev.dest is None or prev.dest == "zero":
            return 0
        if prev.dest not in ins.srcs:
            return 0

        prev_is_load = base_mnem(prev.mnem) in LOADS
        if base_mnem(ins.mnem) in JALR_LIKE:
            self.notes["hazard_jalr"] += 1
            return 2 if prev_is_load else 1
        if prev_is_load:
            self.notes["hazard_load_use"] += 1
            return 1
        return 0

    def run(self, insns):
        total = 0
        for i, ins in enumerate(insns):
            nxt = insns[i + 1] if i + 1 < len(insns) else None
            prev = insns[i - 1] if i > 0 else None
            c = self.insn_cycles(ins, nxt) + self.hazard_penalty(prev, ins)
            total += c
            if self.verbose:
                print(f"  0x{ins.pc:08x} {ins.mnem:<10} {ins.ops:<24} {c:>3}")
        return total


# --------------------------------------------------------------------------
# Region selection
# --------------------------------------------------------------------------

def slice_region(insns, marker="cycle"):
    """Return instructions strictly between the first two CSR reads of `marker`.

    Mirrors how the benchmarks time themselves: two rdcycle reads bracket the
    kernel, so the hardware delta covers exactly the instructions in between.
    """
    idx = [i for i, ins in enumerate(insns)
           if base_mnem(ins.mnem) in CSR_INSNS and marker in ins.ops]
    if len(idx) < 2:
        raise SystemExit(
            f"expected >=2 CSR reads of '{marker}' to delimit the region, found {len(idx)}"
        )
    return insns[idx[0] + 1: idx[1]], idx[0], idx[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="Spike -l trace file")
    ap.add_argument("--marker", default="cycle",
                    help="CSR name bracketing the measured region (default: cycle)")
    ap.add_argument("--whole", action="store_true",
                    help="model the entire trace instead of the bracketed region")
    ap.add_argument("--div-cycles", type=int, default=35,
                    help="cycles charged per div/rem (manual: 3..35, default worst case)")
    ap.add_argument("--actual", type=int, default=None,
                    help="measured RTL cycle count, to report model error")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print per-instruction cycle costs")
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

    model = CV32E40XModel(div_cycles=args.div_cycles, verbose=args.verbose)
    cycles = model.run(region)

    print(f"\nInstructions : {len(region)}")
    print(f"Model cycles : {cycles}")
    if region:
        print(f"Model CPI    : {cycles / len(region):.3f}")

    print("\nInstruction mix / events:")
    for k, v in sorted(model.notes.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v}")

    if model.notes.get("div_rem"):
        print(f"\nNOTE: {model.notes['div_rem']} div/rem in region, each charged "
              f"{args.div_cycles} cycles (manual range 3..35, operand-dependent). "
              f"This is an assumption, not a measurement.")

    if args.actual is not None:
        err = (cycles - args.actual) / args.actual * 100.0
        print(f"\nRTL cycles   : {args.actual}")
        print(f"Model cycles : {cycles}")
        print(f"Error        : {err:+.2f}%")


if __name__ == "__main__":
    main()
