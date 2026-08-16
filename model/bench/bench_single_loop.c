/* Single (non-nested) loop: isolates whether CV32E40P hardware loops work at
 * all, separate from the nested-loop register-ordering problem. */
#include <stdint.h>
#define N 1024
static int32_t va[N], vb[N];

void benchmark_init(void)
{
    for (int i = 0; i < N; i++) { va[i] = (i % 7) - 3; vb[i] = (i % 5) - 2; }
}

int benchmark_run(void)
{
    int32_t acc = 0;
    for (int i = 0; i < N; i++) acc += va[i] * vb[i];   /* one loop level only */
    return acc;
}
