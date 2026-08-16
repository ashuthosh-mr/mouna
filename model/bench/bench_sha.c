/* Fixed-shift-then-add: the `srai a5,15; add a5,a7` idiom that
 * model/find_candidates.py ranked top on Embench edn.
 *
 *   -DUSE_PG_SHA=0   baseline: two instructions
 *   -DUSE_PG_SHA=1   pg.sha rd, rs1, rs2  (opcode 0x7b, funct3=110, funct7=2)
 */
#include <stdint.h>

#define N 1024
static int32_t val[N];
static int32_t add[N];

void benchmark_init(void)
{
    for (int i = 0; i < N; i++) {
        val[i] = (int32_t)((i * 999331u) - 500000000u);   /* varied sign/magnitude */
        add[i] = (int32_t)(i * 7 - 300);
    }
}

int benchmark_run(void)
{
    int32_t acc = 0;
    for (int i = 0; i < N; i++) {
        int32_t x = val[i], y = add[i];
#if USE_PG_SHA
        int32_t r;
        __asm__ (".insn r 0x7b, 6, 2, %0, %1, %2" : "=r"(r) : "r"(x), "r"(y));
#else
        int32_t r = (x >> 15) + y;
#endif
        acc ^= r;
    }
    return acc;
}
