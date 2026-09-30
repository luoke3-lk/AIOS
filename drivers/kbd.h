#ifndef AIOS_DRIVERS_KBD_H_
#define AIOS_DRIVERS_KBD_H_

#include "core/types.h"

#ifndef KBD_MODE
#define KBD_MODE 1
#endif

#define KBD_RING_SIZE 8u
#define LINE_MAX 128u

typedef struct {
    char buf[LINE_MAX + 1u];
    u16 len;
    u16 col0;
} line_t;

int kbd_init(void);
int kbd_has_data(void);
u8 kbd_read_sc(void);
int kbd_poll_key(char *out_ascii, u8 *out_raw);
void kbd_idle(void);
void kbd_set_leds(u8 mask);
void kbd_isr_handler(void);
void line_init(line_t *line, u16 start_col);
int line_feed(line_t *line, char character);
int line_backspace(line_t *line);

#endif  /* AIOS_DRIVERS_KBD_H_ */
