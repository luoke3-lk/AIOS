/* Direct VGA attribute-plane display tests: bars, checkerboard, gradient. */
#include "hw/hw.h"

#include "core/string.h"
#include "drivers/kbd.h"
#include "drivers/vga.h"

static int has_word(const char *text, const char *word) {
    const size_t length = strlen(word);
    while (*text != '\0') {
        if (strncmp(text, word, length) == 0) {
            return 1;
        }
        ++text;
    }
    return 0;
}

static void draw_bars(void) {
    u32 cell = 0u;
    for (cell = 0u; cell < VGA_W * VGA_H; ++cell) {
        const u8 color = (u8)((cell % VGA_W) / 5u);
        VGA_BASE[cell] = (u16)' ' | ((u16)(color << 4u | 0x0Fu) << 8u);
    }
}

static void draw_checker(void) {
    u32 row = 0u;
    u32 column = 0u;
    for (row = 0u; row < VGA_H; ++row) {
        for (column = 0u; column < VGA_W; ++column) {
            const u8 bright = (u8)(((row / 2u) + (column / 4u)) & 1u);
            const u8 attribute = bright != 0u ? 0x1Fu : 0x70u;
            VGA_BASE[row * VGA_W + column] = (u16)' ' | ((u16)attribute << 8u);
        }
    }
}

static void draw_gradient(void) {
    static const char RAMP[] = " .:-=+*#%@";
    u32 cell = 0u;
    for (cell = 0u; cell < VGA_W * VGA_H; ++cell) {
        const u8 level = (u8)((cell % VGA_W) / 8u);
        const u8 attribute = (u8)(0x08u + (level & 7u));
        VGA_BASE[cell] = (u16)(u8)RAMP[level] | ((u16)attribute << 8u);
    }
}

void act_screentest(const char *line, const nn_result_t *result) {
    u32 poll = 0u;
    UNUSED(result);
    if (has_word(line, "grid") || has_word(line, "checker")) {
        draw_checker();
    } else if (has_word(line, "gradient") || has_word(line, "fog")) {
        draw_gradient();
    } else {
        draw_bars();
    }
    vga_move_cursor(0u, 24u);
    for (poll = 0u; poll < 50000u; ++poll) {
        char character = 0;
        u8 raw = 0u;
        if (kbd_poll_key(&character, &raw)) {
            break;
        }
    }
}
