/* CV32E40X testbench reporting. IO helpers live in report_rtl_io.c, linked
   AFTER this file, so report_rtl.o contributes exactly one function to .text
   just as report_spike.o does -- keeping all preceding program code
   byte-identical between the Spike and RTL builds. */
#include <stdint.h>
#define EXIT_ADDR 0x008000c4u
void vp_puts(const char *s);
void vp_putd(int32_t v);

void report(uint32_t cycles, int32_t result)
{
    vp_puts("BENCH cycles=");
    vp_putd((int32_t)cycles);
    vp_puts(" result=");
    vp_putd(result);
    vp_puts("\n");
    *(volatile uint32_t *)EXIT_ADDR = 0;
}
