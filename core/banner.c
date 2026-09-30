/* Startup banner: exact ASCII fixture with dynamic boot metadata inserted. */
#include "drivers/vga.h"

#include "core/string.h"
#include "mm/e820.h"
#include "nn/config.h"

void banner_print(void) {
    const e820_header_t *const map = (const e820_header_t *)E820_HDR_ADDR;
    const boot_info_t *const info = boot_info();
    char number[11];
    const u32 entries = map->magic == E820_MAGIC ? map->count : 0u;

    vga_puts("AIOS v0.1.0 - bare-metal native AI operating system\n");
    vga_puts("(c) 2026 Luo Ke. Every instruction below runs on bare metal.\n\n");
    vga_puts_attr("[boot] mbr at 0x7C00, a20 enabled, e820 probed: ", ATTR_BOOT);
    vga_puts_attr(u32_to_dec(entries, number), ATTR_BOOT);
    vga_puts_attr(" entries\n", ATTR_BOOT);
    vga_puts_attr("[boot] kernel loaded to 0x00010000 (", ATTR_BOOT);
    vga_puts_attr(u32_to_dec(info->sectors_loaded, number), ATTR_BOOT);
    vga_puts_attr(" sectors)\n", ATTR_BOOT);
    vga_puts_attr("[boot] protected mode entered, handing over to ai kernel\n", ATTR_BOOT);
    vga_puts_attr("[kern] vga text 80x25 ready\n", ATTR_KERN);
#if KBD_MODE == 1
    vga_puts_attr("[kern] ps/2 keyboard online (irq1 + hlt)\n", ATTR_KERN);
#else
    vga_puts_attr("[kern] ps/2 keyboard online (polling)\n", ATTR_KERN);
#endif
    /* 网络形状与权重字节数一律从 nn/config.h 推导，杜绝写死后与模型脱节 */
    vga_puts_attr("[kern] int8 mlp ", ATTR_KERN);
    vga_puts_attr(u32_to_dec(NLU_DIM, number), ATTR_KERN);
    vga_puts_attr("-", ATTR_KERN);
    vga_puts_attr(u32_to_dec(NN_HIDDEN, number), ATTR_KERN);
    vga_puts_attr("-", ATTR_KERN);
    vga_puts_attr(u32_to_dec(NN_CLASSES, number), ATTR_KERN);
    vga_puts_attr(" online, ", ATTR_KERN);
    vga_puts_attr(u32_to_dec(WEIGHTS_BYTES, number), ATTR_KERN);
    vga_puts_attr(" bytes of weights in rom\n", ATTR_KERN);
    vga_putc('\n');
    vga_puts("Just tell me what you want to do.\n\n");
}
