/* Immutable HELP/ABOUT fixtures and the low-confidence fallback response. */
#include "hw/hw.h"

#include "drivers/vga.h"
#include "shell/dispatch.h"

void act_help(const char *line, const nn_result_t *result) {
    UNUSED(line);
    UNUSED(result);
    vga_puts(
        "i understand plain english, not commands. just say what you want.\n"
        "things i can do right now:\n"
        "\n"
        "  tell me about my memory        -> e820 map and allocator stats\n"
        "  what cpu is this               -> cpuid vendor, brand, features\n"
        "  run a hardware self test       -> pci scan, memory march, rtc check\n"
        "  is there a disk installed      -> ata identify\n"
        "  what model are you using       -> shape, bit width, rom address\n"
        "  what is 12 times 7             -> integer calculator\n"
        "  test the screen                -> color and pattern test\n"
        "  reboot / shutdown              -> real hardware reset and power off\n"
        "\n"
        "tip: i show my top 3 guesses with confidence before every answer.\n");
}

void act_about(const char *line, const nn_result_t *result) {
    UNUSED(line);
    UNUSED(result);
    vga_puts(
        "AIOS v0.1.0  \"bare metal, nothing underneath\"\n"
        "build      : local@2026-01-01\n"
        "boot chain : bios -> mbr(512B) -> protected mode -> kernel@0x10000\n"
        "toolchain  : keystone-engine + ziglang(x86-freestanding) + unicorn\n"
        "memory     : no os, no scheduler, all ram belongs to the ai engine\n");
}

void act_fallback(const char *line, const nn_result_t *result) {
    u32 rank = 0u;
    UNUSED(line);
    vga_puts_attr("I am not confident enough to touch hardware.\n", ATTR_ERR);
    vga_puts("My three closest guesses were:\n");
    for (rank = 0u; rank < 3u; ++rank) {
        const u8 id = result != NULL ? result->top3_id[rank] : INTENT_HELP;
        vga_puts_attr("  - ", ATTR_HINT);
        vga_puts_attr(intent_name(id), ATTR_HINT);
        vga_puts_attr(": try \"", ATTR_HINT);
        vga_puts_attr(INTENT_TABLE[id < INTENT_COUNT ? id : INTENT_HELP].example, ATTR_HINT);
        vga_puts_attr("\"\n", ATTR_HINT);
    }
    vga_puts_attr("Type help for every available action.\n", ATTR_HINT);
}
