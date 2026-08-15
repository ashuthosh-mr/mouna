#!/usr/bin/env bash
set -euo pipefail
TAG=$1; USE=$2
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
FLAGS="-Os -g -static -mabi=ilp32 -march=rv32imc_zicsr_zifencei -w -nostdlib -nostartfiles
       -DSTACK_TOP=0x00300000 -DUSE_PG_SWPI=$USE"
C="crt.S harness.c bench_swpi.c embench/libc_min.c"
$TC/riscv-none-elf-gcc $FLAGS -T link_rtl.ld -o swpi_${TAG}_rtl.elf $C report_rtl.c report_rtl_io.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-objcopy -O verilog swpi_${TAG}_rtl.elf swpi_${TAG}_rtl.hex
