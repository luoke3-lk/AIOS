/* PCI configuration scan, sampled memory march, and CMOS presence check. */
#include "hw/hw.h"

#include "core/io.h"
#include "core/string.h"
#include "drivers/vga.h"

static u32 pci_read(u8 bus, u8 device, u8 function, u8 offset) {
    const u32 address = 0x80000000u | ((u32)bus << 16u) |
                        ((u32)device << 11u) | ((u32)function << 8u) |
                        ((u32)offset & 0xFCu);
    outl(0x0CF8u, address);
    return inl(0x0CFCu);
}

static int memory_march(void) {
    volatile u32 *const sample = (volatile u32 *)0x00100000u;
    const u32 words = (1024u * 1024u) / 4u;
    u32 index = 0u;
    for (index = 0u; index < words; index += 256u) {
        sample[index] = 0u;
    }
    for (index = 0u; index < words; index += 256u) {
        if (sample[index] != 0u) {
            return -1;
        }
        sample[index] = 0xFFFFFFFFu;
    }
    for (index = 0u; index < words; index += 256u) {
        if (sample[index] != 0xFFFFFFFFu) {
            return -1;
        }
        sample[index] = 0u;
    }
    return 0;
}

void act_selftest(const char *line, const nn_result_t *result) {
    u32 bus = 0u;
    u32 device = 0u;
    u32 function = 0u;
    u32 found = 0u;
    char hex[11];
    u8 seconds = 0u;
    UNUSED(line);
    UNUSED(result);
    vga_puts_attr("Hardware self test\n", ATTR_TITLE);
    for (bus = 0u; bus < 256u; ++bus) {
        for (device = 0u; device < 32u; ++device) {
            for (function = 0u; function < 8u; ++function) {
                const u32 id = pci_read((u8)bus, (u8)device, (u8)function, 0u);
                if ((id & 0xFFFFu) != 0xFFFFu && (id & 0xFFFFu) != 0u) {
                    const u32 class_register = pci_read(
                        (u8)bus, (u8)device, (u8)function, 8u);
                    if (found < 32u) {
                        vga_puts("pci ");
                        vga_puts(u32_to_hex(id & 0xFFFFu, hex));
                        vga_putc(':');
                        vga_puts(u32_to_hex(id >> 16u, hex));
                        vga_puts(" class=");
                        vga_puts(u32_to_hex(class_register >> 8u, hex));
                        vga_putc('\n');
                    }
                    ++found;
                }
            }
        }
    }
    if (found == 0u) {
        vga_puts("no PCI devices found\n");
    }
    vga_puts(memory_march() == 0 ? "memory march: ok\n" : "memory march: failed\n");
    outb(0x70u, 0x00u);
    seconds = inb(0x71u);
    vga_puts("rtc/cmos: ");
    vga_puts(seconds == 0xFFu ? "not detected\n" : "present\n");
}
