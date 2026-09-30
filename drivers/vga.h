#ifndef AIOS_DRIVERS_VGA_H_
#define AIOS_DRIVERS_VGA_H_

#include "core/types.h"

#define VGA_BASE ((volatile u16 *)0x000B8000u)
#define VGA_W 80u
#define VGA_H 25u
#define VGA_SIZE (VGA_W * VGA_H * 2u)
#define CRTC_ADDR 0x03D4u
#define CRTC_DATA 0x03D5u

#define ATTR_DEFAULT 0x07u
#define ATTR_BOOT 0x09u
#define ATTR_KERN 0x0Du
#define ATTR_PROMPT 0x0Fu
#define ATTR_INPUT 0x0Eu
#define ATTR_AI 0x0Au
#define ATTR_META 0x0Bu
#define ATTR_TITLE 0x0Eu
#define ATTR_ERR 0x04u
#define ATTR_HINT 0x08u

void vga_init(void);
void vga_clear(void);
void vga_set_attr(u8 attribute);
u8 vga_get_attr(void);
void vga_putc(char character);
void vga_puts(const char *text);
void vga_puts_attr(const char *text, u8 attribute);
void vga_putn(const char *text, size_t count);
void vga_scroll(void);
void vga_move_cursor(u8 x, u8 y);
void vga_set_cursor_shape(u8 start, u8 end);
void vga_hide_cursor(void);
u8 vga_row(void);
u8 vga_col(void);

#endif  /* AIOS_DRIVERS_VGA_H_ */
