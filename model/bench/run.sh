#!/usr/bin/env bash
# Run one benchmark on Spike (trace -> model) and on CV32E40X RTL (ground
# truth), then report the model's error.
set -euo pipefail
BENCH=${1:?usage: run.sh <bench-name>}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE=/home/kitta/sifive/riscv-isa-sim/build/spike
SPIKE_MEM="-m0xf0000:0x310000,0x80000000:0x400000"
SIMDIR=/home/kitta/paragato/cores/core-v-verif/cv32e40x/sim/core

"$SPIKE" -l --isa=rv32imc_zicntr_zicsr_zifencei $SPIKE_MEM \
    "$HERE/${BENCH}_spike.elf" > "$HERE/${BENCH}.trace" 2>&1

RTL=$(cd "$SIMDIR" && ./testbench_verilator +maxcycles=200000000 \
        "+firmware=$HERE/${BENCH}_rtl.hex" 2>&1 | grep -o 'cycles=[0-9]*' | head -1 | cut -d= -f2)

echo "== $BENCH =="
python3 "$HERE/../cv32e40x_model.py" "$HERE/${BENCH}.trace" --actual "$RTL"
