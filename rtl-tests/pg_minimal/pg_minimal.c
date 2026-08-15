#include "corev_uvmt.h"

int main(void)
{
    volatile int *print = (volatile int *)CV_VP_VIRTUAL_PRINTER_BASE;
    const char *msg = "PG_MINIMAL_OK\n";
    while (*msg)
        *print = *msg++;

    *(volatile int *)(CV_VP_STATUS_FLAGS_BASE + 4) = 0;
    while (1) {}
}
