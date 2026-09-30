#ifndef AIOS_MM_E820_H_
#define AIOS_MM_E820_H_

#include "core/types.h"

#define E820_MAGIC 0x30323845u
#define E820_HDR_ADDR 0x00008000u
#define E820_ENT_ADDR 0x00008010u
#define E820_MAX_ENTRIES 32u
#define E820_ENTRY_SIZE 24u
#define BOOT_INFO_ADDR 0x00000500u

typedef struct PACKED {
    u64 base;
    u64 length;
    u32 type;
    u32 acpi_ext;
} e820_entry_t;

typedef struct PACKED {
    u32 magic;
    u16 count;
    u16 max_entries;
    u64 total_usable;
} e820_header_t;

typedef struct PACKED {
    u16 boot_drive;
    u16 sectors_loaded;
    u32 kernel_bytes;
    u32 a20_method;
    u32 read_method;
} boot_info_t;

STATIC_ASSERT(sizeof(e820_entry_t) == 24u);
STATIC_ASSERT(sizeof(e820_header_t) == 16u);
STATIC_ASSERT(sizeof(boot_info_t) == 16u);

static inline const e820_entry_t *e820_entries(void) {
    return (const e820_entry_t *)E820_ENT_ADDR;
}

static inline const boot_info_t *boot_info(void) {
    return (const boot_info_t *)BOOT_INFO_ADDR;
}

#endif  /* AIOS_MM_E820_H_ */
