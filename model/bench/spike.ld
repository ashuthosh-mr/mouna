/* Bare-metal layout for Spike runs. Spike's default memory region starts at
   0x80000000; keeping every loadable section at or above that avoids the
   fesvr loader rejecting low addresses. */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
  ram (rwxai) : ORIGIN = 0x80000000, LENGTH = 0x200000
}

SECTIONS
{
  . = 0x80000000;

  .text : { *(.text.init) *(.text .text.*) } > ram

  .rodata : { *(.rodata .rodata.*) *(.srodata .srodata.*) } > ram

  .data : { *(.data .data.*) *(.sdata .sdata.*) } > ram

  /* Spike looks up these symbols by name for HTIF termination. */
  .htif ALIGN(64) : { PROVIDE(tohost = .); *(.htif) } > ram

  .bss : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) } > ram

  _end = .;

  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
