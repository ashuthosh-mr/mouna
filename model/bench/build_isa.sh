#!/usr/bin/env bash
# Build a benchmark for a given -march, producing ${NAME}_${TAG}_{spike.elf,rtl.hex}.
set -euo pipefail
NAME=$1; SRC=$2; TAG=$3; MARCH=$4
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
FLAGS="-Os -g -static -mabi=ilp32 -march=$MARCH -w -nostdlib -nostartfiles
       -DSTACK_TOP=0x00300000 -DCPU_MHZ=1 -Iembench"
COMMON="crt.S harness.c embench/adapter.c embench/$SRC embench/beebsc.c embench/libc_min.c"
$TC/riscv-none-elf-gcc $FLAGS -T link_spike.ld -o ${NAME}_${TAG}_spike.elf $COMMON report_spike.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-gcc $FLAGS -T link_rtl.ld   -o ${NAME}_${TAG}_rtl.elf   $COMMON report_rtl.c report_rtl_io.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-objcopy -O verilog ${NAME}_${TAG}_rtl.elf ${NAME}_${TAG}_rtl.hex
