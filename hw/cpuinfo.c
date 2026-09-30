/* CPUID vendor, brand, family/model/stepping, and feature reporting. */
#include "hw/hw.h"

#include "core/string.h"
#include "drivers/vga.h"

static void cpuid(u32 leaf, u32 *eax, u32 *ebx, u32 *ecx, u32 *edx) {
    __asm__ volatile("cpuid"
                     : "=a"(*eax), "=b"(*ebx), "=c"(*ecx), "=d"(*edx)
                     : "a"(leaf), "c"(0u));
}

static void print_number(u32 value) {
    char buffer[11];
    vga_puts(u32_to_dec(value, buffer));
}

void act_cpuinfo(const char *line, const nn_result_t *result) {
    u32 eax = 0u;
    u32 ebx = 0u;
    u32 ecx = 0u;
    u32 edx = 0u;
    u32 max_extended = 0u;
    char vendor[13];
    char brand[49];
    u32 *brand_words = (u32 *)(void *)brand;
    u32 leaf = 0u;
    UNUSED(line);
    UNUSED(result);
    cpuid(0u, &eax, &ebx, &ecx, &edx);
    ((u32 *)(void *)vendor)[0] = ebx;
    ((u32 *)(void *)vendor)[1] = edx;
    ((u32 *)(void *)vendor)[2] = ecx;
    vendor[12] = '\0';
    vga_puts_attr("CPU information\n", ATTR_TITLE);
    vga_puts("vendor   : ");
    vga_puts(vendor);
    vga_putc('\n');
    cpuid(1u, &eax, &ebx, &ecx, &edx);
    vga_puts("family   : ");
    print_number((eax >> 8u) & 0x0Fu);
    vga_puts(" model: ");
    print_number((eax >> 4u) & 0x0Fu);
    vga_puts(" stepping: ");
    print_number(eax & 0x0Fu);
    vga_putc('\n');
    vga_puts("features : FPU=");
    print_number(edx & 1u);
    vga_puts(" MSR=");
    print_number((edx >> 5u) & 1u);
    vga_puts(" APIC=");
    print_number((edx >> 9u) & 1u);
    vga_putc('\n');
    cpuid(0x80000000u, &max_extended, &ebx, &ecx, &edx);
    memset(brand, 0, sizeof(brand));
    if (max_extended >= 0x80000004u) {
        for (leaf = 0u; leaf < 3u; ++leaf) {
            cpuid(0x80000002u + leaf, &brand_words[leaf * 4u],
                  &brand_words[leaf * 4u + 1u], &brand_words[leaf * 4u + 2u],
                  &brand_words[leaf * 4u + 3u]);
        }
        brand[48] = '\0';
        vga_puts("brand    : ");
        vga_puts(brand);
        vga_putc('\n');
    }
}
