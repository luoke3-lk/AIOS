/* Neural-model ROM and fixed AI arena metadata. */
#include "hw/hw.h"

#include "core/string.h"
#include "drivers/vga.h"
#include "mm/pmm.h"
#include "nn/config.h"

#if defined(__has_include)
#if __has_include("nn/model_weights.h")
#define AIOS_HAVE_WEIGHTS 1
#include "nn/model_weights.h"
#endif
#endif
#ifndef AIOS_HAVE_WEIGHTS
#define AIOS_HAVE_WEIGHTS 0
#endif

void act_modelinfo(const char *line, const nn_result_t *result) {
    char address[11];
    char bytes[11];
    u32 weights_address = 0u;
    UNUSED(line);
    UNUSED(result);
#if AIOS_HAVE_WEIGHTS
    weights_address = (u32)&nn_w1[0][0];
#endif
    vga_puts_attr("AI model information\n", ATTR_TITLE);
    /* 形状与权重字节数从 nn/config.h 推导，避免模型和展示文案脱节 */
    vga_puts("shape        : ");
    vga_puts(u32_to_dec(NLU_DIM, bytes));
    vga_puts("x");
    vga_puts(u32_to_dec(NN_HIDDEN, bytes));
    vga_puts("x");
    vga_puts(u32_to_dec(NN_CLASSES, bytes));
    vga_puts("\n");
    vga_puts("quantization : int8 weights / int32 accumulators\n");
    vga_puts("weights      : ");
    vga_puts(u32_to_dec(WEIGHTS_BYTES, bytes));
    vga_puts(" bytes\nweights @   : ");
    vga_puts(u32_to_hex(weights_address, address));
    vga_puts("\nai exclusive : ");
    vga_puts(u32_to_dec(pmm_ai_kb(), bytes));
    vga_puts(" KiB\n");
}
