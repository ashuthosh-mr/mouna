#!/usr/bin/env bash
# The two builds differ only in report_{spike,rtl}.c, which link last. So all
# .text before report() is the actual program and must be byte-identical for a
# model-vs-RTL cycle comparison to be meaningful on this alignment-sensitive core.
set -euo pipefail
NAME=$1
TC=/home/kitta/sifive/xpack-riscv-none-elf-gcc-14.2.0-3/bin
off() { local e=$1 s=$2
  local a t
  a=$($TC/riscv-none-elf-nm $e | awk -v n="$s" '$3==n{print $1}')
  t=$($TC/riscv-none-elf-nm $e | awk '$3=="_start"{print $1}')
  echo $(( 0x$a - 0x$t )); }
OS=$(off ${NAME}_spike.elf report); OR=$(off ${NAME}_rtl.elf report)
$TC/riscv-none-elf-objcopy -O binary --only-section=.text ${NAME}_spike.elf .s.bin
$TC/riscv-none-elf-objcopy -O binary --only-section=.text ${NAME}_rtl.elf   .r.bin
N=$(( OS < OR ? OS : OR ))
head -c $N .s.bin > .sc.bin; head -c $N .r.bin > .rc.bin
if [ "$OS" != "$OR" ]; then echo "[$NAME] LAYOUT MISMATCH: report at $OS vs $OR"; rm -f .s.bin .r.bin .sc.bin .rc.bin; exit 1; fi
if cmp -s .sc.bin .rc.bin; then echo "[$NAME] program .text identical ($N bytes) -- comparison valid"
else echo "[$NAME] .text DIFFERS"; rm -f .s.bin .r.bin .sc.bin .rc.bin; exit 1; fi
rm -f .s.bin .r.bin .sc.bin .rc.bin
