/* MD5-style variable rotate-left, the `sll; sub; srl; or` idiom that
 * model/find_candidates.py ranked top on Embench md5sum (4.2% of cycles).
 *
 *   -DUSE_PG_ROL=0   baseline: four instructions
 *   -DUSE_PG_ROL=1   pg.rol rd, rs1, rs2  (opcode 0x7b, funct3=110, funct7=1)
 */
#include <stdint.h>

#define N 1024
static uint32_t val[N];
static uint32_t amt[N];

void benchmark_init(void)
{
    for (int i = 0; i < N; i++) {
        val[i] = (uint32_t)(i * 2654435761u);
        amt[i] = (uint32_t)(i % 31) + 1;      /* 1..31, avoids the n==0 case */
    }
}

int benchmark_run(void)
{
    uint32_t acc = 0;
    for (int i = 0; i < N; i++) {
        uint32_t x = val[i], n = amt[i];
#if USE_PG_ROL
        uint32_t r;
        __asm__ (".insn r 0x7b, 6, 1, %0, %1, %2" : "=r"(r) : "r"(x), "r"(n));
#else
        uint32_t r = (x << n) | (x >> (32 - n));
#endif
        acc ^= r;
    }
    return (int)acc;
}
