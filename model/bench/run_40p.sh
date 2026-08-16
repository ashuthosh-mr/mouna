#!/usr/bin/env bash
# Trace one kernel on Spike and run it on CV32E40P RTL, then report model error.
set -euo pipefail
NAME=${1:?}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE=/home/kitta/sifive/riscv-isa-sim/build/spike
MEM="-m0x40000:0x100000,0x80000000:0x400000"
SIMDIR=/home/kitta/paragato/cores/core-v-verif/cv32e40p/sim/core
TB=$(cd "$SIMDIR" && find . -name verilator_executable | head -1)

"$SPIKE" -l --log-commits --isa=rv32imc_zicntr_zicsr_zifencei $MEM \
    "$HERE/${NAME}_40p_spike.elf" > "$HERE/${NAME}_40p.trace" 2>&1
RTL=$(cd "$SIMDIR" && $TB +maxcycles=200000000 \
        "+firmware=$HERE/${NAME}_40p_rtl.hex" 2>&1 | grep -o 'cycles=[0-9]*' | head -1 | cut -d= -f2)
python3 "$HERE/../cv32e40p_model.py" "$HERE/${NAME}_40p.trace" --actual "$RTL"
