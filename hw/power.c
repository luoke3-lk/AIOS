/* Hardware power controls. Destructive actions intentionally need no confirm. */
#include "hw/hw.h"

#include "core/io.h"
#include "drivers/vga.h"

void act_reboot(const char *line, const nn_result_t *result) {
    struct PACKED {
        u16 limit;
        u32 base;
    } null_idt = {0u, 0u};
    UNUSED(line);
    UNUSED(result);
    cpu_cli();
    outb(0x64u, 0xFEu);
    /* If the 8042 reset pulse is ignored, deliberately provoke triple fault. */
    __asm__ volatile("lidt %0\nint $3" : : "m"(null_idt));
    for (;;) {
        cpu_hlt();
    }
}

void act_shutdown(const char *line, const nn_result_t *result) {
    UNUSED(line);
    UNUSED(result);
    /* Protected mode cannot safely call a real-mode BIOS. Try common ACPI/QEMU
     * power ports, then provide a deterministic halted fallback. */
    outw(0x0604u, 0x2000u);
    outw(0xB004u, 0x2000u);
    vga_puts("It is now safe to turn off your computer.\n");
    cpu_cli();
    for (;;) {
        cpu_hlt();
    }
}
