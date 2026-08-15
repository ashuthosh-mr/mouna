/* Spike: terminate via HTIF. Results are not printed; the Spike run exists only
   to produce the instruction trace. */
#include <stdint.h>
volatile uint64_t tohost   __attribute__((section(".htif"), aligned(64)));
volatile uint64_t fromhost __attribute__((section(".htif"), aligned(64)));

volatile uint32_t g_cycles;
volatile int32_t  g_result;

void report(uint32_t cycles, int32_t result)
{
    g_cycles = cycles;
    g_result = result;
    tohost = 1;
}
