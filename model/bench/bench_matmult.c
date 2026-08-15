/* 8x8 integer matrix multiply. */
#define N 8
static int a[N][N], b[N][N], c[N][N];

void benchmark_init(void)
{
    int k = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            a[i][j] = (k % 7) - 3;
            b[i][j] = (k % 5) - 2;
            k++;
        }
}

int benchmark_run(void)
{
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            int sum = 0;
            for (int k = 0; k < N; k++)
                sum += a[i][k] * b[k][j];
            c[i][j] = sum;
        }
    int checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += c[i][j];
    return checksum;
}
