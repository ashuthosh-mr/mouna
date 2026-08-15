/* Spike build. All data sections are pinned to fixed absolute addresses that
   match link_rtl.ld exactly, so every absolute address the compiler
   materialises is identical in both builds. Combined with PC-relative control
   flow, this makes the timed code byte-identical -- required because CV32E40X
   branch timing depends on instruction alignment. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x80000000;
  .text   : { *(.text.init) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) *(.srodata .srodata.*) }
  . = 0x00100000; .data : { *(.data .data.*) *(.sdata .sdata.*) }
  . = 0x00110000; .bss  : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
  . = 0x00120000; .htif ALIGN(64) : { PROVIDE(tohost = .); *(.htif) }
  _end = .;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
