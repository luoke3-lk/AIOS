#ifndef AIOS_SHELL_DISPATCH_H_
#define AIOS_SHELL_DISPATCH_H_

#include "core/types.h"
#include "hw/hw.h"
#include "shell/intent.h"

typedef struct {
    u8 id;
    const char *name;
    const char *desc;
    const char *example;
    intent_fn fn;
} intent_entry_t;

extern const intent_entry_t INTENT_TABLE[INTENT_COUNT];
void dispatch(u8 id, const char *line, const nn_result_t *result);
const char *intent_name(u8 id);

#endif  /* AIOS_SHELL_DISPATCH_H_ */
