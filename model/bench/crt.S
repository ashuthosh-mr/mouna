/* Shared bare-metal entry for both the Spike and CV32E40X RTL builds. */
    .section .text.init
    .global _start
_start:
    li   sp, STACK_TOP
    call bench_main
1:  j    1b
