/* Unified bare-metal kernel used for BOTH Spike tracing and CV32E40X RTL.
 *
 * Why one source, two link bases: instruction alignment changes cycle counts on
 * CV32E40X (a taken branch costs 3 cycles, or 4 when the target is a
 * non-word-aligned non-RVC instruction). Two separately-written harnesses put
 * the loop at different offsets and therefore genuinely execute at different
 * cycle counts, which invalidates any model-vs-RTL comparison.
 *
 * So: identical code, identical layout, and everything that differs between the
 * two targets is placed strictly AFTER the timed region, leaving the kernel's
 * offsets (and hence its alignment) bit-identical in both builds.
 */
#include <stdint.h>

#define N 8

static int a[N][N], b[N][N], c[N][N];

static void init(void)
{
    int k = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            a[i][j] = (k % 7) - 3;
            b[i][j] = (k % 5) - 2;
            k++;
        }
}

static void matmult(void)
{
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            int sum = 0;
            for (int k = 0; k < N; k++)
                sum += a[i][k] * b[k][j];
            c[i][j] = sum;
        }
}

static inline uint32_t rdcycle(void)
{
    uint32_t v;
    __asm__ volatile ("rdcycle %0" : "=r"(v) : : "memory");
    return v;
}

#ifdef SPIKE_HARNESS
volatile uint64_t tohost   __attribute__((section(".htif"), aligned(64)));
volatile uint64_t fromhost __attribute__((section(".htif"), aligned(64)));
#else
#define PRINT_ADDR 0x00800000u
#define EXIT_ADDR  0x008000c4u
#endif

/* Results are stashed in globals so the reporting code below the timed region
   cannot influence the region's code layout. */
volatile uint32_t g_cycles;
volatile int32_t  g_checksum;

void bench_main(void)
{
    init();

    uint32_t start = rdcycle();
    matmult();
    uint32_t end = rdcycle();

    /* ---- everything below here is outside the measured region ---- */
    int32_t checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += c[i][j];

    g_cycles = end - start;
    g_checksum = checksum;

#ifdef SPIKE_HARNESS
    tohost = 1;
#else
    {
        /* minimal unsigned decimal print through the testbench print peripheral */
        volatile uint32_t *p = (volatile uint32_t *)PRINT_ADDR;
        const char *tag = "KERNEL cycles=";
        while (*tag) *p = *tag++;
        uint32_t v = g_cycles;
        char buf[12];
        int n = 0;
        if (v == 0) buf[n++] = '0';
        while (v) { buf[n++] = (char)('0' + (v % 10)); v /= 10; }
        while (n) *p = buf[--n];
        const char *tag2 = " checksum=";
        while (*tag2) *p = *tag2++;
        int32_t s = g_checksum;
        if (s < 0) { *p = '-'; s = -s; }
        n = 0;
        if (s == 0) buf[n++] = '0';
        while (s) { buf[n++] = (char)('0' + (s % 10)); s /= 10; }
        while (n) *p = buf[--n];
        *p = '\n';
        *(volatile uint32_t *)EXIT_ADDR = 0;
    }
#endif
    for (;;) { }
}
