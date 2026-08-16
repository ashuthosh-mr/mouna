/* Calibrates Xpulp instruction costs against RTL, same method as
 * pg_mulcost: dependent chains, compared against a documented 1-cycle
 * baseline (plain add), so the delta is the real hardware cost, not a guess.
 */
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

/* pg_matmult-style print via the CV32E40P testbench print peripheral. */
#define PRINT_ADDR 0x10000000u
#define EXIT_ADDR  0x20000004u
static void puts_vp(const char *s) {
    volatile uint32_t *p = (volatile uint32_t *)PRINT_ADDR;
    while (*s) *p = (uint32_t)*s++;
}
static void putd_vp(int32_t v) {
    volatile uint32_t *p = (volatile uint32_t *)PRINT_ADDR;
    char buf[12]; int n = 0; uint32_t u = v < 0 ? (uint32_t)-v : (uint32_t)v;
    if (v < 0) *p = '-';
    if (u == 0) buf[n++] = '0';
    while (u) { buf[n++] = (char)('0' + (u % 10)); u /= 10; }
    while (n) *p = (uint32_t)buf[--n];
}

void bench_main(void)
{
    uint32_t v, w, start, end, t_empty, t_add, t_mac;

    v = 3; w = 5;
    start = rdcycle(); end = rdcycle();
    t_empty = end - start;

    v = 3;
    start = rdcycle();
    REP256(__asm__ volatile ("add %0,%0,%1" : "+r"(v) : "r"(w));)
    end = rdcycle();
    t_add = end - start;

    v = 3;
    start = rdcycle();
    REP256(__asm__ volatile (".insn r 0x33, 0, 0x21, %0, %1, %1" : "+r"(v) : "r"(w));)
    end = rdcycle();
    t_mac = end - start;

    puts_vp("PG_XPULP_CAL");
    puts_vp(" empty="); putd_vp(t_empty);
    puts_vp(" add=");   putd_vp(t_add);
    puts_vp(" mac=");   putd_vp(t_mac);
    puts_vp(" sink=");  putd_vp(v);
    puts_vp("\n");
    *(volatile uint32_t *)EXIT_ADDR = 0;
    for (;;) {}
}
