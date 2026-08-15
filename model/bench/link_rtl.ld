/* CV32E40X testbench build. Data addresses pinned identically to
   link_spike.ld; only .text's base differs (testbench boots at 0x80). */
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x00000080;
  .text   : { *(.text.init) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) *(.srodata .srodata.*) }
  . = 0x00100000; .data : { *(.data .data.*) *(.sdata .sdata.*) }
  . = 0x00110000; .bss  : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
  _end = .;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
