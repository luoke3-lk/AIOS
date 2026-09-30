/*
 * Physical frame allocator backed by a fixed bitmap at 0x40000. A set bit is
 * unavailable or allocated. Allocation statistics count dynamic ownership,
 * not firmware-reserved frames, so callers can observe exact round trips.
 */
#include "mm/pmm.h"

#include "core/string.h"

static volatile u8 *const PMM_BITMAP = (volatile u8 *)PMM_BITMAP_ADDR;
static u32 g_frame_limit = 0u;
static u32 g_usable_frames = 0u;
static u32 g_allocated_frames = 0u;
static u32 g_search_hint = 256u;
static size_t g_bitmap_size = 0u;

static void bit_set(u32 frame) {
    PMM_BITMAP[frame >> 3u] |= (u8)(1u << (frame & 7u));
}

static void bit_clear(u32 frame) {
    PMM_BITMAP[frame >> 3u] &= (u8)~(1u << (frame & 7u));
}

static int bit_test(u32 frame) {
    return (PMM_BITMAP[frame >> 3u] & (u8)(1u << (frame & 7u))) != 0u;
}

static u32 e820_end_frame(const e820_entry_t *entry) {
    const u32 *words = (const u32 *)(const void *)entry;
    const u32 base_low = words[0];
    const u32 base_high = words[1];
    const u32 length_low = words[2];
    const u32 length_high = words[3];
    u32 end = 0u;
    if (base_high != 0u) {
        return 0u;
    }
    end = base_low + length_low;
    if (length_high != 0u || end < base_low) {
        return 0x00100000u;
    }
    return (end + PMM_FRAME_SIZE - 1u) >> 12u;
}

static void mark_usable(u32 first, u32 last) {
    u32 frame = 0u;
    if (first < 256u) {
        first = 256u;
    }
    if (last > g_frame_limit) {
        last = g_frame_limit;
    }
    for (frame = first; frame < last; ++frame) {
        if (bit_test(frame)) {
            bit_clear(frame);
            ++g_usable_frames;
        }
    }
}

void pmm_init(const e820_header_t *header) {
    const e820_entry_t *entries = e820_entries();
    u32 count = 0u;
    u32 index = 0u;
    g_frame_limit = 0u;
    g_usable_frames = 0u;
    g_allocated_frames = 0u;
    g_search_hint = 256u;
    if (header != NULL && header->magic == E820_MAGIC) {
        count = header->count;
        if (count > E820_MAX_ENTRIES) {
            count = E820_MAX_ENTRIES;
        }
        for (index = 0u; index < count; ++index) {
            const u32 last = e820_end_frame(&entries[index]);
            if (entries[index].type == 1u && last > g_frame_limit) {
                g_frame_limit = last;
            }
        }
    }
    if (g_frame_limit <= 256u) {
        g_frame_limit = 16384u;
    }
    if (g_frame_limit > 0x00100000u) {
        g_frame_limit = 0x00100000u;
    }
    g_bitmap_size = (g_frame_limit + 7u) >> 3u;
    if (g_bitmap_size > PMM_BITMAP_MAX_BYTES) {
        g_bitmap_size = PMM_BITMAP_MAX_BYTES;
        g_frame_limit = PMM_BITMAP_MAX_BYTES * 8u;
    }
    memset((void *)PMM_BITMAP, 0xFF, g_bitmap_size);
    if (count == 0u) {
        mark_usable(256u, g_frame_limit);
    } else {
        for (index = 0u; index < count; ++index) {
            if (entries[index].type == 1u) {
                const u32 *words = (const u32 *)(const void *)&entries[index];
                const u32 first = (words[0] + PMM_FRAME_SIZE - 1u) >> 12u;
                mark_usable(first, e820_end_frame(&entries[index]));
            }
        }
    }
}

u32 pmm_alloc_frame(void) {
    u32 pass = 0u;
    u32 frame = 0u;
    for (pass = 0u; pass < 2u; ++pass) {
        const u32 begin = pass == 0u ? g_search_hint : 256u;
        const u32 end = pass == 0u ? g_frame_limit : g_search_hint;
        for (frame = begin; frame < end; ++frame) {
            if (!bit_test(frame)) {
                bit_set(frame);
                ++g_allocated_frames;
                g_search_hint = frame + 1u;
                return frame << 12u;
            }
        }
    }
    return 0u;
}

void pmm_free_frame(u32 address) {
    const u32 frame = address >> 12u;
    if ((address & (PMM_FRAME_SIZE - 1u)) != 0u || frame < 256u || frame >= g_frame_limit) {
        return;
    }
    if (bit_test(frame)) {
        bit_clear(frame);
        if (g_allocated_frames > 0u) {
            --g_allocated_frames;
        }
        if (frame < g_search_hint) {
            g_search_hint = frame;
        }
    }
}

u32 pmm_total_frames(void) {
    return g_usable_frames;
}

u32 pmm_used_frames(void) {
    return g_allocated_frames;
}

u32 pmm_total_kb(void) {
    return g_usable_frames * 4u;
}

u32 pmm_used_kb(void) {
    return g_allocated_frames * 4u;
}

u32 pmm_ai_kb(void) {
    const u32 used = pmm_used_kb();
    const u32 total = pmm_total_kb();
    return total > used ? total - used : 0u;
}

size_t pmm_bitmap_bytes(void) {
    return g_bitmap_size;
}
