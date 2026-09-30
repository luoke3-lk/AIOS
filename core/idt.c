/* Minimal protected-mode IDT: default stubs plus the keyboard IRQ gate. */
#include "core/idt.h"

#include "core/types.h"
#include "drivers/kbd.h"

#if KBD_MODE == 1

typedef struct PACKED {
    u16 offset_low;
    u16 selector;
    u8 zero;
    u8 flags;
    u16 offset_high;
} idt_gate_t;

typedef struct PACKED {
    u16 limit;
    u32 base;
} idt_ptr_t;

static idt_gate_t g_idt[256];

__attribute__((naked)) static void isr_stub(void) {
    __asm__ volatile("iret");
}

__attribute__((naked)) static void kbd_isr(void) {
    __asm__ volatile(
        "pusha\n"
        "call kbd_isr_handler\n"
        "popa\n"
        "iret\n");
}

static void idt_set_gate(u8 vector, void (*handler)(void)) {
    const u32 address = (u32)handler;
    g_idt[vector].offset_low = (u16)(address & 0xFFFFu);
    g_idt[vector].selector = 0x0008u;
    g_idt[vector].zero = 0u;
    g_idt[vector].flags = 0x8Eu;
    g_idt[vector].offset_high = (u16)(address >> 16u);
}

void idt_init(void) {
    idt_ptr_t descriptor;
    u32 vector = 0u;
    for (vector = 0u; vector < 256u; ++vector) {
        idt_set_gate((u8)vector, isr_stub);
    }
    idt_set_gate(0x21u, kbd_isr);
    descriptor.limit = (u16)(sizeof(g_idt) - 1u);
    descriptor.base = (u32)&g_idt[0];
    __asm__ volatile("lidt %0" : : "m"(descriptor));
}

#else

void idt_init(void) {
}

#endif
