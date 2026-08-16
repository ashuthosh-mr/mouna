/* Table-driven CRC32 -- the kernel whose table-address sequence
 * (`andi; mv; slli; add`) model/find_candidates.py ranked top on Embench crc32.
 *
 *   -DUSE_PG_IDX=0   baseline: index computed with four instructions
 *   -DUSE_PG_IDX=1   pg.idx rd, rs1, rs2  ->  rd = rs2 + ((rs1 & 0xff) << 2)
 *
 * pg.idx encoding: opcode 0x7b (OPCODE_HWLOOP), funct3=111, funct7=0000000.
 * Emitted with .insn so no toolchain change is needed.
 */
#include <stdint.h>

#define NBYTES 1024
static uint32_t table[256];
static uint8_t  data[NBYTES];

void benchmark_init(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        table[i] = c;
    }
    for (int i = 0; i < NBYTES; i++) data[i] = (uint8_t)(i * 31 + 7);
}

int benchmark_run(void)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (int i = 0; i < NBYTES; i++) {
        uint32_t idx = crc ^ data[i];
#if USE_PG_IDX
        /* one instruction: addr = &table[0] + ((idx & 0xff) << 2) */
        const uint32_t *ent;
        __asm__ (".insn r 0x7b, 7, 0, %0, %1, %2"
                 : "=r"(ent) : "r"(idx), "r"(table));
        crc = *ent ^ (crc >> 8);
#else
        crc = table[idx & 0xff] ^ (crc >> 8);
#endif
    }
    return (int)(crc ^ 0xFFFFFFFFu);
}
