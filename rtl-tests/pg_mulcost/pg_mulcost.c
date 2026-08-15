/* Per-instruction cost calibration for the CV32E40X model.
 *
 * Runs straight-line dependent chains of a single instruction type and times
 * them with rdcycle. Comparing a `mul` chain against an `add` chain (identical
 * dependency structure, add is a documented 1-cycle integer op) isolates the
 * real hardware cost of `mul` rather than trusting the user manual's table.
 */
#include <stdio.h>
#include <stdint.h>

#define REP4(x)   x x x x
#define REP16(x)  REP4(REP4(x))
#define REP256(x) REP16(REP16(x))
#define NREP 256

static inline uint32_t rdcycle(void)
{
    uint32_t c;
    __asm__ volatile ("rdcycle %0" : "=r"(c) : : "memory");
    return c;
}

int main(void)
{
    uint32_t v = 3, w = 5, start, end;
    uint32_t t_add, t_mul, t_mulh, t_empty;

    /* empty: measures the fixed overhead of the two rdcycle reads themselves */
    start = rdcycle();
    end = rdcycle();
    t_empty = end - start;

    v = 3; w = 5;
    start = rdcycle();
    REP256(__asm__ volatile ("add %0,%0,%1" : "+r"(v) : "r"(w));)
    end = rdcycle();
    t_add = end - start;

    v = 3; w = 5;
    start = rdcycle();
    REP256(__asm__ volatile ("mul %0,%0,%1" : "+r"(v) : "r"(w));)
    end = rdcycle();
    t_mul = end - start;

    v = 3; w = 5;
    start = rdcycle();
    REP256(__asm__ volatile ("mulh %0,%0,%1" : "+r"(v) : "r"(w));)
    end = rdcycle();
    t_mulh = end - start;

    printf("PG_MULCOST n=%d\n", NREP);
    printf("  empty=%lu\n", (unsigned long)t_empty);
    printf("  add  =%lu  per=%lu.%02lu\n", (unsigned long)t_add,
           (unsigned long)(t_add / NREP), (unsigned long)((t_add % NREP) * 100 / NREP));
    printf("  mul  =%lu  per=%lu.%02lu\n", (unsigned long)t_mul,
           (unsigned long)(t_mul / NREP), (unsigned long)((t_mul % NREP) * 100 / NREP));
    printf("  mulh =%lu  per=%lu.%02lu\n", (unsigned long)t_mulh,
           (unsigned long)(t_mulh / NREP), (unsigned long)((t_mulh % NREP) * 100 / NREP));
    printf("  sink=%lu\n", (unsigned long)v);
    return 0;
}
