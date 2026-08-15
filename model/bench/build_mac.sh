#!/usr/bin/env bash
set -euo pipefail
TAG=$1; USEMAC=$2
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
FLAGS="-Os -g -static -mabi=ilp32 -march=rv32imc_zicsr_zifencei -w -nostdlib -nostartfiles
       -DSTACK_TOP=0x00300000 -DUSE_PG_MAC=$USEMAC"
C="crt.S harness.c bench_mac.c"
$TC/riscv-none-elf-gcc $FLAGS -T link_spike.ld -o mac_${TAG}_spike.elf $C report_spike.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-gcc $FLAGS -T link_rtl.ld   -o mac_${TAG}_rtl.elf   $C report_rtl.c report_rtl_io.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-objcopy -O verilog mac_${TAG}_rtl.elf mac_${TAG}_rtl.hex
