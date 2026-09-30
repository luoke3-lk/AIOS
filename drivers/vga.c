/*
 * VGA 80x25 text driver. Character and attribute are written atomically as a
 * 16-bit cell. Hardware cursor blinking is configured once by the CRTC.
 */
#include "drivers/vga.h"

#include "core/io.h"
#include "core/string.h"

static u8 g_attribute = ATTR_DEFAULT;
static u8 g_row = 0u;
static u8 g_column = 0u;

static u16 vga_cell(char character, u8 attribute) {
    return (u16)(u8)character | ((u16)attribute << 8u);
}

static void vga_sync_cursor(void) {
    vga_move_cursor(g_column, g_row);
}

void vga_move_cursor(u8 x, u8 y) {
    const u16 position = (u16)y * (u16)VGA_W + (u16)x;
    outb(CRTC_ADDR, 0x0Eu);
    outb(CRTC_DATA, (u8)(position >> 8u));
    outb(CRTC_ADDR, 0x0Fu);
    outb(CRTC_DATA, (u8)(position & 0xFFu));
}

void vga_set_cursor_shape(u8 start, u8 end) {
    outb(CRTC_ADDR, 0x0Au);
    outb(CRTC_DATA, (u8)(start & 0x1Fu));
    outb(CRTC_ADDR, 0x0Bu);
    outb(CRTC_DATA, (u8)(end & 0x1Fu));
}

void vga_hide_cursor(void) {
    outb(CRTC_ADDR, 0x0Au);
    outb(CRTC_DATA, 0x20u);
}

void vga_clear(void) {
    u32 cell = 0u;
    for (cell = 0u; cell < VGA_W * VGA_H; ++cell) {
        VGA_BASE[cell] = vga_cell(' ', ATTR_DEFAULT);
    }
    g_attribute = ATTR_DEFAULT;
    g_row = 0u;
    g_column = 0u;
    vga_sync_cursor();
}

void vga_init(void) {
    vga_clear();
    vga_set_cursor_shape(0x0Du, 0x0Eu);
    vga_sync_cursor();
}

void vga_set_attr(u8 attribute) {
    g_attribute = attribute;
}

u8 vga_get_attr(void) {
    return g_attribute;
}

void vga_scroll(void) {
    u32 cell = 0u;
    for (cell = 0u; cell < VGA_W * (VGA_H - 1u); ++cell) {
        VGA_BASE[cell] = VGA_BASE[cell + VGA_W];
    }
    for (cell = VGA_W * (VGA_H - 1u); cell < VGA_W * VGA_H; ++cell) {
        VGA_BASE[cell] = vga_cell(' ', g_attribute);
    }
    g_row = VGA_H - 1u;
    g_column = 0u;
}

void vga_putc(char character) {
    if (character == '\n') {
        g_column = 0u;
        ++g_row;
    } else if (character == '\r') {
        g_column = 0u;
    } else if (character == '\t') {
        u8 spaces = (u8)(4u - (g_column & 3u));
        while (spaces-- > 0u) {
            vga_putc(' ');
        }
        return;
    } else if (character == '\b') {
        if (g_column > 0u) {
            --g_column;
        } else if (g_row > 0u) {
            --g_row;
            g_column = VGA_W - 1u;
        } else {
            return;
        }
        VGA_BASE[(u32)g_row * VGA_W + g_column] = vga_cell(' ', ATTR_DEFAULT);
    } else if ((u8)character >= 0x20u && (u8)character <= 0x7Eu) {
        VGA_BASE[(u32)g_row * VGA_W + g_column] = vga_cell(character, g_attribute);
        ++g_column;
    }
    if (g_column >= VGA_W) {
        g_column = 0u;
        ++g_row;
    }
    if (g_row >= VGA_H) {
        vga_scroll();
    }
    vga_sync_cursor();
}

void vga_puts(const char *text) {
    while (*text != '\0') {
        vga_putc(*text++);
    }
}

void vga_puts_attr(const char *text, u8 attribute) {
    const u8 saved = g_attribute;
    g_attribute = attribute;
    vga_puts(text);
    g_attribute = saved;
}

void vga_putn(const char *text, size_t count) {
    size_t index = 0u;
    for (index = 0u; index < count; ++index) {
        vga_putc(text[index]);
    }
}

u8 vga_row(void) {
    return g_row;
}

u8 vga_col(void) {
    return g_column;
}
