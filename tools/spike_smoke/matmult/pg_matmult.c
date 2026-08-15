#include <stdio.h>
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

/* "memory" clobber forces a full compiler barrier so init()/checksum/printf
   can never be reordered across a timing read into the measured window. */
static inline uint32_t rdcycle(void)
{
    uint32_t c;
    __asm__ volatile ("rdcycle %0" : "=r"(c) : : "memory");
    return c;
}

int main(void)
{
    init();
    uint32_t start = rdcycle();
    matmult();
    uint32_t end = rdcycle();

    long checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += c[i][j];

    printf("PG_MATMULT checksum=%ld cycles=%lu\n", checksum, (unsigned long)(end - start));
    return 0;
}
