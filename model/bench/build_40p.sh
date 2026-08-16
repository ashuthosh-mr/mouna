#!/usr/bin/env bash
# Build one Embench kernel twice for CV32E40P -- Spike (trace) and RTL (ground
# truth) -- with identical .text so the comparison is valid.
set -euo pipefail
NAME=${1:?usage: build_40p.sh <name> <src.c>}
SRC=${2:?}
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
FLAGS="-Os -g -static -mabi=ilp32 -march=rv32imc_zicsr_zifencei -w -nostdlib -nostartfiles
       -DSTACK_TOP=0x00070000 -DCPU_MHZ=1 -Iembench"
COMMON="crt.S harness.c embench/adapter.c embench/$SRC embench/beebsc.c embench/libc_min.c"
$TC/riscv-none-elf-gcc $FLAGS -T link_spike_40p.ld -o ${NAME}_40p_spike.elf $COMMON report_spike.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-gcc $FLAGS -T link_rtl_40p.ld   -o ${NAME}_40p_rtl.elf   $COMMON report_rtl_40p.c report_rtl_io_40p.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-objcopy -O verilog ${NAME}_40p_rtl.elf ${NAME}_40p_rtl.hex
