/* Minimal bare-metal entry for running kernels under Spike (no proxy kernel).
   Spike's default memory starts at 0x80000000, so we link there and put the
   stack well inside that region. */
    .section .text.init
    .global _start
_start:
    li   sp, 0x80200000
    call bench_main
1:  j    1b
