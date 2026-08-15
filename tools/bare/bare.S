    .section .text.start
    .global _start
_start:
    li   sp, 0x003FFF00          # stack well inside RAM
    li   t0, 0x00800000          # CV_VP_VIRTUAL_PRINTER_BASE
    la   t1, msg
1:  lbu  t2, 0(t1)
    beqz t2, 2f
    sw   t2, 0(t0)
    addi t1, t1, 1
    j    1b
2:  li   t0, 0x008000c4          # CV_VP_STATUS_FLAGS_BASE + 4  (exit reg)
    li   t2, 0
    sw   t2, 0(t0)
3:  j    3b
msg:
    .asciz "PG_BARE_OK\n"
