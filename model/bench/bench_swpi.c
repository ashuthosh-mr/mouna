/* Post-increment store kernel: measures pg.swpi against the plain
 *   sw rs2, 0(p) ; p += 4
 * sequence it replaces.
 *
 *   -DUSE_PG_SWPI=0  plain store + pointer bump
 *   -DUSE_PG_SWPI=1  single pg.swpi offloaded over CV-X-IF (uses xif_mem)
 *
 * pg.swpi: R-type custom-0, funct7=0000000 funct3=001 opcode=0001011
 *          mem[rs1] <- rs2 ; rd <- rs1 + 4     (used with rd == rs1)
 */
#include <stdint.h>

#define N 1024
static int32_t dst[N];

void benchmark_init(void)
{
    for (int i = 0; i < N; i++) dst[i] = 0;
}

int benchmark_run(void)
{
    int32_t *p = dst;
    for (int i = 0; i < N; i++) {
#if USE_PG_SWPI
        __asm__ volatile (".insn r 0x0b, 1, 0, %0, %0, %1"
                          : "+r"(p) : "r"(i) : "memory");
#else
        *p = i;
        p++;
#endif
    }
    int32_t sum = 0;
    for (int i = 0; i < N; i += 128) sum += dst[i];
    return sum;
}
