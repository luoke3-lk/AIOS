/* Clear-screen and E820/allocator reporting actions. */
#include "hw/hw.h"

#include "core/string.h"
#include "drivers/vga.h"
#include "mm/e820.h"
#include "mm/pmm.h"

static void print_u32(u32 value) {
    char buffer[11];
    vga_puts(u32_to_dec(value, buffer));
}

void act_clear(const char *line, const nn_result_t *result) {
    UNUSED(line);
    UNUSED(result);
    vga_clear();
}

void act_meminfo(const char *line, const nn_result_t *result) {
    const e820_header_t *const header = (const e820_header_t *)E820_HDR_ADDR;
    const e820_entry_t *const entries = e820_entries();
    u32 count = 0u;
    u32 index = 0u;
    char address[19];
    UNUSED(line);
    UNUSED(result);
    if (header->magic == E820_MAGIC) {
        count = header->count > E820_MAX_ENTRIES ? E820_MAX_ENTRIES : header->count;
    }
    vga_puts_attr("E820 memory map\n", ATTR_TITLE);
    for (index = 0u; index < count; ++index) {
        vga_puts("  base=");
        vga_puts(u64_to_hex(entries[index].base, address));
        vga_puts(" length=");
        vga_puts(u64_to_hex(entries[index].length, address));
        vga_puts(" type=");
        print_u32(entries[index].type);
        vga_putc('\n');
    }
    if (count == 0u) {
        vga_puts_attr("[warn] e820 unavailable, using fallback map\n", ATTR_ERR);
    }
    vga_puts("total usable : ");
    print_u32(pmm_total_kb());
    vga_puts(" KiB\nused frames  : ");
    print_u32(pmm_used_kb());
    vga_puts(" KiB\nfree         : ");
    print_u32(pmm_total_kb() - pmm_used_kb());
    vga_puts(" KiB\nai exclusive : ");
    print_u32(pmm_ai_kb());
    vga_puts(" KiB (>=90%)\n");
}
