#ifndef AIOS_CORE_GLOBALS_H_
#define AIOS_CORE_GLOBALS_H_

#include "core/types.h"

extern volatile u32 g_canary_head;
extern char g_shell_line_storage[129];
extern volatile u32 g_kbd_overflow;
extern volatile u32 g_canary_tail;

#endif  /* AIOS_CORE_GLOBALS_H_ */
