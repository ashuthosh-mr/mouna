/* Minimal freestanding libc subset: the Embench kernels use a handful of
   string.h routines, and we build with -nostdlib. */
#include <stddef.h>
void *memset(void *d, int c, size_t n)
{ unsigned char *p = d; while (n--) *p++ = (unsigned char)c; return d; }
void *memcpy(void *d, const void *s, size_t n)
{ unsigned char *p = d; const unsigned char *q = s; while (n--) *p++ = *q++; return d; }
int memcmp(const void *a, const void *b, size_t n)
{ const unsigned char *x = a, *y = b; while (n--) { if (*x != *y) return *x - *y; x++; y++; } return 0; }
size_t strlen(const char *s) { const char *p = s; while (*p) p++; return (size_t)(p - s); }
