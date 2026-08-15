/* Proves a brand-new custom instruction can be added to CV32E40P by decoder
 * change alone -- no extension interface involved.
 *
 *   pg.add3 rd, rs1, rs2   ->   rd = rs1 + rs2
 *   R-type, opcode 0x7b, funct3=000, funct7=0000000
 *
 * Returns 0 if the custom instruction agrees with a plain add on every input
 * tested, non-zero otherwise -- so a wrong result is distinguishable from a
 * hang or an illegal-instruction trap.
 */
#include <stdint.h>

void benchmark_init(void) { }

int benchmark_run(void)
{
    int errors = 0;
    for (int32_t i = 0; i < 64; i++) {
        int32_t a = i * 7 - 13;
        int32_t b = i * -3 + 5;
        int32_t got;
        __asm__ volatile (".insn r 0x7b, 0, 0, %0, %1, %2"
                          : "=r"(got) : "r"(a), "r"(b));
        if (got != a + b) errors++;
    }
    return errors;
}
