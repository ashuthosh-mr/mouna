/* Indexed byte load: the `add; lbu` idiom that find_candidates.py ranked top
 * on Embench matmult-int (3,200 executions, 2.4%). Unlike pg.idx/pg.rol/pg.sha
 * this needs no new RTL at all -- CV32E40P's Xpulp mode already implements a
 * native register-register indexed load (opcode LOAD, funct3=111,
 * funct7=0100000 for byte-unsigned). This validates the finder against
 * hardware that already exists, rather than hardware built to match it.
 *
 *   -DUSE_PG_LBX=0   baseline: add then lbu (two instructions)
 *   -DUSE_PG_LBX=1   single reg-reg indexed load
 */
#include <stdint.h>

#define N 1024
static uint8_t buf[N + 256];
static int32_t idx[N];

void benchmark_init(void)
{
    for (int i = 0; i < N + 256; i++) buf[i] = (uint8_t)(i * 37 + 11);
    for (int i = 0; i < N; i++) idx[i] = i % 200;
}

int benchmark_run(void)
{
    uint32_t acc = 0;
    uint8_t *base = buf;
    for (int i = 0; i < N; i++) {
        int32_t off = idx[i];
#if USE_PG_LBX
        /* uint32_t, not uint8_t: funct7=0x20 is the *unsigned* byte form, so
           the instruction already zero-extends. Declaring the output as
           uint8_t makes GCC emit a redundant `zext.b`, which cancels the
           instruction the fusion saved -- measured as exactly zero speedup. */
        uint32_t v;
        __asm__ (".insn r 0x03, 7, 0x20, %0, %1, %2" : "=r"(v) : "r"(base), "r"(off));
#else
        uint32_t v = base[off];
#endif
        acc += v;
    }
    return (int)acc;
}
