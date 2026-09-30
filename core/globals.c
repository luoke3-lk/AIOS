/* Shared small buffers live in .bss/.data; large arenas use fixed addresses. */
#include "core/globals.h"

volatile u32 g_canary_head = 0xCAFEBABEu;
char g_shell_line_storage[129] = {0};
volatile u32 g_kbd_overflow = 0u;
volatile u32 g_canary_tail = 0xDEADBEEFu;
