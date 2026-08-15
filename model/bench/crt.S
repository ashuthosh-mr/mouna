/* Shared bare-metal entry for both Spike and CV32E40X RTL builds.
 *
 * The 2-byte pad below compensates for the one remaining code-length
 * difference between the two link bases (small addresses materialise with a
 * shorter sequence than 0x8xxxxxxx ones). Without it the two builds place the
 * inner loop at different alignments, and on CV32E40X a taken branch costs 3
 * or 4 cycles depending on whether its target is a word-aligned/RVC
 * instruction -- so the two builds would genuinely execute at different cycle
 * counts and could not be compared. */
    .section .text.init
    .global _start
_start:
#ifdef SPIKE_HARNESS
    c.nop                      /* 2-byte layout compensation, see above */
#endif
    li   sp, STACK_TOP
    call bench_main
1:  j    1b
