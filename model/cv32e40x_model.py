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

# `spike --log-commits` emits, after each instruction, the architectural state it
# wrote, e.g.
#   core   0: 3 0x800000b4 (0x03756533) x10 0x00000000
# Replaying these lets us reconstruct the register file, which is what makes the
# real div/rem operand (and hence its true cycle cost) recoverable.
COMMIT_RE = re.compile(
    r"core\s+\d+:\s+\d+\s+0x[0-9a-fA-F]+\s+\(0x[0-9a-fA-F]+\)\s+x(\d+)\s+0x([0-9a-fA-F]+)"
)


def clz32(v):
    """Leading zeros of a 32-bit value; clz(0) == 32."""
    v &= 0xFFFFFFFF
    if v == 0:
        return 32
    return 32 - v.bit_length()


class Insn:
    __slots__ = ("pc", "enc", "size", "mnem", "ops", "dest", "srcs", "div_operand")

    def __init__(self, pc, enc, enc_str, mnem, ops):
        self.div_operand = None
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
    """Parse a `spike -l` trace, optionally enriched with `--log-commits`.

    When commit lines are present we replay register writes so that the divisor
    of each div/rem can be read out of the reconstructed register file. Without
    them the model has to assume a worst-case divide, which is the single
    largest source of over-prediction on divide-heavy code.
    """
    insns = []
    regs = [0] * 32
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = TRACE_RE.match(line)
            if m:
                pc_s, enc_s, mnem, ops = m.groups()
                ins = Insn(int(pc_s, 16), int(enc_s, 16), enc_s, mnem, ops.strip())
                if base_mnem(mnem) in DIV_REM and ins.size == 4:
                    # R-type: rs2 = enc[24:20]. Read it *before* this
                    # instruction's own writeback is replayed.
                    ins.div_operand = regs[(ins.enc >> 20) & 0x1F]
                insns.append(ins)
                continue
            c = COMMIT_RE.match(line)
            if c:
                rd, val = int(c.group(1)), int(c.group(2), 16)
                if rd:  # x0 stays zero
                    regs[rd] = val
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
        # Cycles above the IPC=1 ideal, attributed to microarchitectural cause.
        self.stalls = Counter()

    def target_penalty(self, nxt):
        """+1 cycle when a control-flow target is a non-word-aligned,
        non-RVC (32-bit) instruction."""
        if nxt is None:
            return 0
        if (nxt.pc % 4) != 0 and nxt.size == 4:
            return 1
        return 0

    def insn_cycles(self, ins, nxt):
        """Cycles for one instruction.

        Every instruction costs a baseline 1 cycle (the IPC=1 ideal for this
        single-issue in-order pipeline); anything above that is recorded in
        self.stalls under the microarchitectural cause, so the total decomposes
        as: cycles = instructions + sum(stalls).
        """
        b = base_mnem(ins.mnem)

        if b in FENCES:
            self.notes["fence"] += 1
            pen = self.target_penalty(nxt)
            self.stalls["fence"] += 4
            self.stalls["target_misalign"] += pen
            return 5 + pen

        if b in CSR_INSNS:
            self.notes["csr"] += 1
            return 1  # 4 only for jvt, which we do not use

        if b in DIV_REM:
            self.notes["div_rem"] += 1
            if ins.div_operand is not None:
                # Manual: 3 cycles when the divisor has no leading zeros, 35 when
                # the divisor is 0 -- i.e. 3 + clz(divisor).
                self.notes["div_rem_exact"] += 1
                c = 3 + clz32(ins.div_operand)
            else:
                c = self.div_cycles
            self.stalls["div_multicycle"] += c - 1
            return c

        if b in MUL_HIGH:
            self.notes["mulh"] += 1
            self.stalls["mul_multicycle"] += 3
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
                pen = self.target_penalty(nxt)
                self.stalls["branch_flush"] += 2
                self.stalls["target_misalign"] += pen
                return 3 + pen
            self.notes["branch_not_taken"] += 1
            return 1

        if b in JUMPS:
            self.notes["jump"] += 1
            pen = self.target_penalty(nxt)
            self.stalls["jump_flush"] += 1
            self.stalls["target_misalign"] += pen
            return 2 + pen

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
            p = 2 if prev_is_load else 1
            self.stalls["raw_jalr"] += p
            return p
        if prev_is_load:
            self.notes["hazard_load_use"] += 1
            self.stalls["raw_load_use"] += 1
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

    # Where the cycles went: cycles = instructions (IPC=1 ideal) + stalls.
    n = len(region)
    stall_total = sum(model.stalls.values())
    print("\nCycle breakdown (cycles = compute + stalls):")
    print(f"  {'compute (1/instr)':<22} {n:>10}  {100.0*n/cycles:5.1f}%")
    for k, v in sorted(model.stalls.items(), key=lambda kv: -kv[1]):
        if v:
            print(f"  {'stall: ' + k:<22} {v:>10}  {100.0*v/cycles:5.1f}%")
    print(f"  {'-- total stalls':<22} {stall_total:>10}  {100.0*stall_total/cycles:5.1f}%")
    ideal = n
    print(f"\n  ideal cycles (IPC=1)  {ideal}")
    print(f"  achieved IPC          {n/cycles:.3f}   "
          f"(headroom to IPC=1: {100.0*stall_total/cycles:.1f}% of cycles)")

    print("\nInstruction mix / events:")
    for k, v in sorted(model.notes.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v}")

    n_div = model.notes.get("div_rem", 0)
    n_exact = model.notes.get("div_rem_exact", 0)
    if n_div and n_exact < n_div:
        print(f"\nNOTE: {n_div - n_exact} of {n_div} div/rem had no recoverable divisor "
              f"and were charged the worst case ({args.div_cycles} cycles; manual range "
              f"3..35). Re-run spike with --log-commits so the model can read the "
              f"actual operands.")
    elif n_exact:
        print(f"\n{n_exact} div/rem costed exactly from recovered divisors "
              f"(3 + leading-zeros, per the manual).")

    if args.actual is not None:
        err = (cycles - args.actual) / args.actual * 100.0
        print(f"\nRTL cycles   : {args.actual}")
        print(f"Model cycles : {cycles}")
        print(f"Error        : {err:+.2f}%")


if __name__ == "__main__":
    main()
