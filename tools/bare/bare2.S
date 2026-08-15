    .section .text.start
    .global _start
_start:
    li   sp, 0x003FFF00
    li   t0, 0x00800000      # print peripheral
    li   t2, 0x41            # 'A'  -- no loads at all
    sw   t2, 0(t0)
    li   t2, 0x42            # 'B'
    sw   t2, 0(t0)
    li   t2, 0x0A            # newline
    sw   t2, 0(t0)
    # now test a LOAD from .text data
    la   t1, val
    lw   t3, 0(t1)
    sw   t3, 0(t0)           # print whatever we loaded
    li   t0, 0x008000c4
    li   t2, 0
    sw   t2, 0(t0)
1:  j    1b
    .align 2
val:
    .word 0x00000043         # 'C'
