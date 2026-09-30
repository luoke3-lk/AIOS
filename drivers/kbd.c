/*
 * PS/2 Set-1 keyboard decoder shared by polling and IRQ modes. The IRQ path
 * only enqueues raw scan codes; all stateful decoding stays in the main loop.
 */
#include "drivers/kbd.h"

#include "core/globals.h"
#include "core/io.h"

#if KBD_MODE == 1
#include "core/idt.h"
#include "core/pic.h"
#endif

static const char KBD_PLAIN[128] = {
    0, 27, '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', '\b', 0,
    'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\n', 0, 'a', 's',
    'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\'', '`', 0, '\\', 'z', 'x', 'c', 'v',
    'b', 'n', 'm', ',', '.', '/', 0, '*', 0, ' ', 0, 0, 0, 0, 0,
};

static const char KBD_SHIFTED[128] = {
    0, 27, '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+', '\b', 0,
    'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '{', '}', '\n', 0, 'A', 'S',
    'D', 'F', 'G', 'H', 'J', 'K', 'L', ':', '"', '~', 0, '|', 'Z', 'X', 'C', 'V',
    'B', 'N', 'M', '<', '>', '?', 0, '*', 0, ' ', 0, 0, 0, 0, 0,
};

static volatile u8 g_ring[KBD_RING_SIZE];
static volatile u8 g_ring_read = 0u;
static volatile u8 g_ring_write = 0u;
static u8 g_shift = 0u;
static u8 g_caps = 0u;
static u8 g_extended = 0u;

static int ring_empty(void) {
    return g_ring_read == g_ring_write;
}

static void ring_push(u8 scan_code) {
    const u8 next = (u8)((g_ring_write + 1u) & (KBD_RING_SIZE - 1u));
    if (next == g_ring_read) {
        g_kbd_overflow = 1u;
        return;
    }
    g_ring[g_ring_write] = scan_code;
    g_ring_write = next;
}

static int ring_pop(u8 *scan_code) {
    if (ring_empty()) {
        return 0;
    }
    *scan_code = g_ring[g_ring_read];
    g_ring_read = (u8)((g_ring_read + 1u) & (KBD_RING_SIZE - 1u));
    return 1;
}

static void kbd_wait_input_clear(void) {
    u32 timeout = 100000u;
    while (timeout-- > 0u && (inb(0x64u) & 0x02u) != 0u) {
        io_wait();
    }
}

void kbd_set_leds(u8 mask) {
    kbd_wait_input_clear();
    outb(0x60u, 0xEDu);
    kbd_wait_input_clear();
    outb(0x60u, mask);
}

int kbd_init(void) {
    g_ring_read = 0u;
    g_ring_write = 0u;
    g_shift = 0u;
    g_caps = 0u;
    g_extended = 0u;
#if KBD_MODE == 1
    idt_init();
    pic_init_keyboard_only();
    cpu_sti();
#endif
    return 0;
}

int kbd_has_data(void) {
#if KBD_MODE == 1
    if (!ring_empty()) {
        return 1;
    }
#endif
    return (inb(0x64u) & 0x01u) != 0u;
}

u8 kbd_read_sc(void) {
    return inb(0x60u);
}

void kbd_isr_handler(void) {
    ring_push(kbd_read_sc());
    outb(0x20u, 0x20u);
}

static int kbd_next_scan(u8 *scan_code) {
#if KBD_MODE == 1
    cpu_cli();
    if (ring_pop(scan_code)) {
        cpu_sti();
        return 1;
    }
    cpu_sti();
#endif
    if (kbd_has_data()) {
        *scan_code = kbd_read_sc();
        return 1;
    }
    return 0;
}

int kbd_poll_key(char *out_ascii, u8 *out_raw) {
    u8 scan_code = 0u;
    char character = 0;
    if (out_ascii == NULL || out_raw == NULL || !kbd_next_scan(&scan_code)) {
        return 0;
    }
    *out_raw = scan_code;
    *out_ascii = 0;
    if (scan_code == 0xE0u) {
        g_extended = 1u;
        return 0;
    }
    if ((scan_code & 0x80u) != 0u) {
        const u8 released = (u8)(scan_code & 0x7Fu);
        if (released == 0x2Au || released == 0x36u) {
            g_shift = 0u;
        }
        g_extended = 0u;
        return 0;
    }
    if (g_extended != 0u) {
        g_extended = 0u;
        return 0;
    }
    if (scan_code == 0x2Au || scan_code == 0x36u) {
        g_shift = 1u;
        return 0;
    }
    if (scan_code == 0x3Au) {
        g_caps ^= 1u;
        kbd_set_leds((u8)(g_caps << 2u));
        return 0;
    }
    if (scan_code >= ARRAY_SIZE(KBD_PLAIN)) {
        return 0;
    }
    character = g_shift != 0u ? KBD_SHIFTED[scan_code] : KBD_PLAIN[scan_code];
    if (g_caps != 0u && character >= 'a' && character <= 'z') {
        character = (char)(character - ('a' - 'A'));
    } else if (g_caps != 0u && g_shift != 0u && character >= 'A' && character <= 'Z') {
        character = (char)(character + ('a' - 'A'));
    }
    if (character == 0) {
        return 0;
    }
    *out_ascii = character;
    return 1;
}

void kbd_idle(void) {
#if KBD_MODE == 1
    cpu_sti();
    cpu_hlt();
#endif
}

void line_init(line_t *line, u16 start_col) {
    if (line == NULL) {
        return;
    }
    line->len = 0u;
    line->col0 = start_col;
    line->buf[0] = '\0';
}

int line_feed(line_t *line, char character) {
    if (line == NULL || line->len >= LINE_MAX || character < 0x20 || character > 0x7E) {
        return -1;
    }
    line->buf[line->len++] = character;
    line->buf[line->len] = '\0';
    return 0;
}

int line_backspace(line_t *line) {
    if (line == NULL || line->len == 0u) {
        return 0;
    }
    --line->len;
    line->buf[line->len] = '\0';
    return 1;
}
