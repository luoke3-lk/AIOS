#ifndef AIOS_MM_PMM_H_
#define AIOS_MM_PMM_H_

#include "core/types.h"
#include "mm/e820.h"

#define PMM_FRAME_SIZE 4096u
#define PMM_BITMAP_ADDR 0x00040000u
#define PMM_BITMAP_MAX_BYTES (128u * 1024u)
#define PMM_AI_ARENA_ADDR 0x00060000u
#define PMM_AI_ARENA_BYTES (128u * 1024u)

void pmm_init(const e820_header_t *header);
u32 pmm_alloc_frame(void);
void pmm_free_frame(u32 address);
u32 pmm_total_frames(void);
u32 pmm_used_frames(void);
u32 pmm_total_kb(void);
u32 pmm_used_kb(void);
u32 pmm_ai_kb(void);
size_t pmm_bitmap_bytes(void);

#endif  /* AIOS_MM_PMM_H_ */
