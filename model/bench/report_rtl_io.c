#include <stdint.h>
#define PRINT_ADDR 0x00800000u
void vp_puts(const char *s)
{
    volatile uint32_t *p = (volatile uint32_t *)PRINT_ADDR;
    while (*s) *p = (uint32_t)*s++;
}
void vp_putd(int32_t v)
{
    volatile uint32_t *p = (volatile uint32_t *)PRINT_ADDR;
    char buf[12]; int n = 0; uint32_t u;
    if (v < 0) { *p = '-'; u = (uint32_t)(-(int64_t)v); } else u = (uint32_t)v;
    if (u == 0) buf[n++] = '0';
    while (u) { buf[n++] = (char)('0' + (u % 10)); u /= 10; }
    while (n) *p = (uint32_t)buf[--n];
}
