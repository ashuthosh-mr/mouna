OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x80000000 + 0x80;
  .text : { *(.text.init) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) *(.srodata .srodata.*) }
  . = 0x80100000;
  .data : { *(.data .data.*) *(.sdata .sdata.*) }
  .htif ALIGN(64) : { PROVIDE(tohost = .); *(.htif) }
  .bss : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
  _end = .;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
