/* Spike bare-metal harness for the pg_matmult kernel.
 *
 * The kernel body here must stay byte-identical to
 * rtl-tests/pg_matmult/pg_matmult.c so that the instruction sequence between
 * the two rdcycle reads is the same on Spike and on CV32E40X RTL. Only the
 * surrounding startup/exit differs, and that lies outside the measured window.
 *
 * Build with the SAME flags core-v-verif uses for the RTL build:
 *   -Os -mabi=ilp32 -march=rv32imc_zicsr_zifencei
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

/* "memory" clobber forces a full compiler barrier so init()/checksum can never
   be reordered across a timing read into the measured window. */
static inline uint32_t rdcycle(void)
{
    uint32_t c;
    __asm__ volatile ("rdcycle %0" : "=r"(c) : : "memory");
    return c;
}

/* Spike HTIF exit. Writing (code<<1)|1 to tohost terminates the simulation. */
volatile uint64_t tohost   __attribute__((section(".htif"), aligned(64)));
volatile uint64_t fromhost __attribute__((section(".htif"), aligned(64)));

void bench_main(void)
{
    init();
    uint32_t start = rdcycle();
    matmult();
    uint32_t end = rdcycle();

    long checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += c[i][j];

    /* Keep results observable so nothing is optimised away. */
    volatile long sink_sum = checksum;
    volatile uint32_t sink_cyc = end - start;
    (void)sink_sum;
    (void)sink_cyc;

    tohost = 1;
    for (;;) { }
}
