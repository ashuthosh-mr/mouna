#!/usr/bin/env bash
# Build an Embench kernel twice (Spike + CV32E40X RTL) with identical timed code.
set -euo pipefail
NAME=${1:?usage: build_embench.sh <name> <src.c>}
SRC=${2:?}
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
FLAGS="-Os -g -static -mabi=ilp32 -march=rv32imc_zicsr_zifencei -w -nostdlib -nostartfiles
       -DSTACK_TOP=0x00300000 -DCPU_MHZ=1 -Iembench"
COMMON="crt.S harness.c embench/adapter.c embench/$SRC embench/beebsc.c embench/libc_min.c"
$TC/riscv-none-elf-gcc $FLAGS -T link_spike.ld -o ${NAME}_spike.elf $COMMON report_spike.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-gcc $FLAGS -T link_rtl.ld   -o ${NAME}_rtl.elf   $COMMON report_rtl.c report_rtl_io.c 2>&1 |  grep -v RWX || true
$TC/riscv-none-elf-objcopy -O verilog ${NAME}_rtl.elf ${NAME}_rtl.hex

# Layout equality is checked separately by verify_layout.sh
