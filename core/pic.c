/* Remap both 8259 PICs and unmask only IRQ1 (PS/2 keyboard). */
#include "core/pic.h"

#include "core/io.h"

void pic_init_keyboard_only(void) {
    outb(0x20u, 0x11u);
    io_wait();
    outb(0xA0u, 0x11u);
    io_wait();
    outb(0x21u, 0x20u);
    io_wait();
    outb(0xA1u, 0x28u);
    io_wait();
    outb(0x21u, 0x04u);
    io_wait();
    outb(0xA1u, 0x02u);
    io_wait();
    outb(0x21u, 0x01u);
    io_wait();
    outb(0xA1u, 0x01u);
    io_wait();
    outb(0x21u, 0xFDu);
    outb(0xA1u, 0xFFu);
}
