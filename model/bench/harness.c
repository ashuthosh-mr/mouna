/* Target-independent benchmark harness.
 *
 * Everything here is identical in the Spike and RTL builds. All target-specific
 * output lives in report_{spike,rtl}.c, which link AFTER this object so they
 * cannot perturb the code layout (and hence instruction alignment) of the timed
 * region. */
#include <stdint.h>

extern void benchmark_init(void);
extern int  benchmark_run(void);
extern void report(uint32_t cycles, int32_t result);

static inline uint32_t rdcycle(void)
{
    uint32_t v;
    __asm__ volatile ("rdcycle %0" : "=r"(v) : : "memory");
    return v;
}

void bench_main(void)
{
    benchmark_init();

    uint32_t start = rdcycle();
    int result = benchmark_run();
    uint32_t end = rdcycle();

    report(end - start, (int32_t)result);
    for (;;) { }
}
