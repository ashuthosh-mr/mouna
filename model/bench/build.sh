#!/usr/bin/env bash
# Build one benchmark twice -- once for Spike, once for CV32E40X RTL -- with
# identical .text so that a model trace from Spike can be compared against RTL
# cycle counts on this alignment-sensitive core.
set -euo pipefail
BENCH=${1:?usage: build.sh <bench-c-file-without-extension>}
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
FLAGS="-Os -g -static -mabi=ilp32 -march=rv32imc_zicsr_zifencei -Wall -nostdlib -nostartfiles -DSTACK_TOP=0x00300000"
$TC/riscv-none-elf-gcc $FLAGS -T link_spike.ld -o ${BENCH}_spike.elf crt.S harness.c ${BENCH}.c report_spike.c 2>&1 | grep -v RWX || true
$TC/riscv-none-elf-gcc $FLAGS -T link_rtl.ld   -o ${BENCH}_rtl.elf   crt.S harness.c ${BENCH}.c report_rtl.c report_rtl_io.c 2>&1 |  grep -v RWX || true
$TC/riscv-none-elf-objcopy -O verilog ${BENCH}_rtl.elf ${BENCH}_rtl.hex

# Verify the TIMED function (benchmark_run) is byte-identical between builds.
# Code after the second rdcycle (the report() call and its target) may legally
# differ; only the measured region must match, since CV32E40X timing is
# alignment-sensitive.
cmp_fn() {
    local elf=$1 out=$2
    local addr size tstart
    addr=$($TC/riscv-none-elf-nm -S $elf | awk '/ benchmark_run$/{print $1}')
    size=$($TC/riscv-none-elf-nm -S $elf | awk '/ benchmark_run$/{print $2}')
    tstart=$($TC/riscv-none-elf-nm $elf | awk '/ T _start$/{print $1}')
    $TC/riscv-none-elf-objcopy -O binary --only-section=.text $elf .tmp.bin
    dd if=.tmp.bin of=$out bs=1 skip=$(( 0x$addr - 0x$tstart )) count=$(( 0x$size )) status=none
    echo $(( 0x$addr - 0x$tstart )) $(( 0x$size ))
}
cmp_fn ${BENCH}_spike.elf .fs.bin > /dev/null
cmp_fn ${BENCH}_rtl.elf   .fr.bin > /dev/null
if cmp -s .fs.bin .fr.bin; then
    echo "[$BENCH] timed benchmark_run() byte-identical ($(stat -c%s .fs.bin) bytes) -- comparison valid"
else
    echo "[$BENCH] WARNING: timed benchmark_run() DIFFERS -- comparison invalid"
    rm -f .tmp.bin .fs.bin .fr.bin; exit 1
fi
rm -f .tmp.bin .fs.bin .fr.bin
