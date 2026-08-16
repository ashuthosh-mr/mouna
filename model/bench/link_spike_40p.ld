/* CV32E40P Spike build: .text high (Spike's loader rejects low addresses), data
   pinned identically to link_rtl_40p.ld. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x80000000;
  .text   : { *(.text.init) *(.text .text.*) }
  . = 0x00080000; .rodata : { *(.rodata .rodata.*) *(.srodata .srodata.*) }
  . = 0x00090000; .data   : { *(.data .data.*) *(.sdata .sdata.*) }
  . = 0x000A0000; .bss    : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
  . = 0x000B0000; .htif ALIGN(64) : { PROVIDE(tohost = .); *(.htif) }
  _end = .;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
