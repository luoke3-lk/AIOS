#ifndef AIOS_CORE_IO_H_
#define AIOS_CORE_IO_H_

#include "core/types.h"

static inline u8 inb(u16 port) {
    u8 value = 0;
    __asm__ volatile("inb %w1, %0" : "=a"(value) : "Nd"(port));
    return value;
}

static inline u16 inw(u16 port) {
    u16 value = 0;
    __asm__ volatile("inw %w1, %0" : "=a"(value) : "Nd"(port));
    return value;
}

static inline u32 inl(u16 port) {
    u32 value = 0;
    __asm__ volatile("inl %w1, %0" : "=a"(value) : "Nd"(port));
    return value;
}

static inline void outb(u16 port, u8 value) {
    __asm__ volatile("outb %0, %w1" : : "a"(value), "Nd"(port));
}

static inline void outw(u16 port, u16 value) {
    __asm__ volatile("outw %0, %w1" : : "a"(value), "Nd"(port));
}

static inline void outl(u16 port, u32 value) {
    __asm__ volatile("outl %0, %w1" : : "a"(value), "Nd"(port));
}

static inline void io_wait(void) {
    outb(0x80u, 0u);
}

static inline void cpu_cli(void) {
    __asm__ volatile("cli" : : : "memory");
}

static inline void cpu_sti(void) {
    __asm__ volatile("sti" : : : "memory");
}

static inline void cpu_hlt(void) {
    __asm__ volatile("hlt");
}

#endif  /* AIOS_CORE_IO_H_ */
