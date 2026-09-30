/*
 * Protected-mode kernel entry. The MBR establishes a flat GDT before jumping
 * here. The entry owns stack setup so no compiler-generated prologue runs on
 * the BIOS stack.
 */
#include "core/types.h"
#include "drivers/kbd.h"
#include "drivers/vga.h"
#include "mm/e820.h"
#include "mm/pmm.h"
#include "shell/shell.h"

extern u8 _bss_start;
extern u8 _bss_end;

void banner_print(void);

__attribute__((noinline)) void start_clear_bss(void) {
    u8 *cursor = &_bss_start;
    while (cursor < &_bss_end) {
        *cursor++ = 0u;
    }
}

void kernel_main(void) {
    const e820_header_t *const memory_map = (const e820_header_t *)E820_HDR_ADDR;
    vga_init();
    pmm_init(memory_map);
    (void)kbd_init();
    banner_print();
    shell_run();
}

__attribute__((naked, used, section(".text.start"))) void _start(void) {
    __asm__ volatile(
        "movl $0x00090000, %esp\n"
        "xorl %ebp, %ebp\n"
        "call start_clear_bss\n"
        "call kernel_main\n"
        "cli\n"
        "1: hlt\n"
        "jmp 1b\n");
}
