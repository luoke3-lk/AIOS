/* ATA PIO IDENTIFY with bounded polling and a small static result cache. */
#include "hw/hw.h"

#include "core/io.h"
#include "core/string.h"
#include "drivers/vga.h"

#define ATA_TIMEOUT 1000000u

typedef struct {
    int scanned;
    int present;
    char model[41];
    char serial[21];
    u32 sectors;
} ata_cache_t;

static ata_cache_t g_cache = {0, 0, {0}, {0}, 0u};

static void ata_copy_swapped(char *output, const u16 *words, u32 count) {
    u32 index = 0u;
    u32 end = count * 2u;
    for (index = 0u; index < count; ++index) {
        output[index * 2u] = (char)(words[index] >> 8u);
        output[index * 2u + 1u] = (char)(words[index] & 0xFFu);
    }
    while (end > 0u && output[end - 1u] == ' ') {
        --end;
    }
    output[end] = '\0';
}

static int ata_identify(u16 io_base, u8 slave, u16 identify[256]) {
    u32 timeout = ATA_TIMEOUT;
    u32 index = 0u;
    u8 status = 0u;
    outb((u16)(io_base + 6u), (u8)(0xA0u | (slave << 4u)));
    outb((u16)(io_base + 2u), 0u);
    outb((u16)(io_base + 3u), 0u);
    outb((u16)(io_base + 4u), 0u);
    outb((u16)(io_base + 5u), 0u);
    outb((u16)(io_base + 7u), 0xECu);
    status = inb((u16)(io_base + 7u));
    if (status == 0u || status == 0xFFu) {
        return -1;
    }
    while (timeout-- > 0u) {
        status = inb((u16)(io_base + 7u));
        if ((status & 0x01u) != 0u) {
            return -1;
        }
        if ((status & 0x80u) == 0u && (status & 0x08u) != 0u) {
            for (index = 0u; index < 256u; ++index) {
                identify[index] = inw(io_base);
            }
            return 0;
        }
    }
    return -1;
}

static void scan_once(void) {
    static const u16 BASES[2] = {0x01F0u, 0x0170u};
    u16 identify[256];
    u32 controller = 0u;
    u32 slave = 0u;
    g_cache.scanned = 1;
    for (controller = 0u; controller < 2u; ++controller) {
        for (slave = 0u; slave < 2u; ++slave) {
            if (ata_identify(BASES[controller], (u8)slave, identify) == 0) {
                g_cache.present = 1;
                ata_copy_swapped(g_cache.serial, &identify[10], 10u);
                ata_copy_swapped(g_cache.model, &identify[27], 20u);
                g_cache.sectors = (u32)identify[60] | ((u32)identify[61] << 16u);
                return;
            }
        }
    }
}

void act_diskinfo(const char *line, const nn_result_t *result) {
    char number[11];
    UNUSED(line);
    UNUSED(result);
    if (!g_cache.scanned) {
        scan_once();
    }
    vga_puts_attr("ATA disk information\n", ATTR_TITLE);
    if (!g_cache.present) {
        vga_puts("no ATA device\n");
        return;
    }
    vga_puts("model   : ");
    vga_puts(g_cache.model);
    vga_puts("\nserial  : ");
    vga_puts(g_cache.serial);
    vga_puts("\nsectors : ");
    vga_puts(u32_to_dec(g_cache.sectors, number));
    vga_putc('\n');
}
