#ifndef AIOS_HW_HW_H_
#define AIOS_HW_HW_H_

#include "core/types.h"

#if defined(__has_include)
#if __has_include("nn/config.h") && __has_include("nn/model_weights.h") && __has_include("nn/nn.h")
#include "nn/nn.h"
#define AIOS_HAVE_NN_RESULT 1
#endif
#endif

#ifndef AIOS_HAVE_NN_RESULT
#define AIOS_NN_CLASSES 12u

typedef struct {
    s32 logits[AIOS_NN_CLASSES];
    u8 top3_id[3];
    u8 top3_pct[3];
    u8 top1;
} nn_result_t;
#else
#define AIOS_NN_CLASSES NN_CLASSES
#endif

typedef void (*intent_fn)(const char *line, const nn_result_t *result);

void act_clear(const char *line, const nn_result_t *result);
void act_meminfo(const char *line, const nn_result_t *result);
void act_cpuinfo(const char *line, const nn_result_t *result);
void act_selftest(const char *line, const nn_result_t *result);
void act_diskinfo(const char *line, const nn_result_t *result);
void act_modelinfo(const char *line, const nn_result_t *result);
void act_calc(const char *line, const nn_result_t *result);
void act_screentest(const char *line, const nn_result_t *result);
void act_help(const char *line, const nn_result_t *result);
void act_about(const char *line, const nn_result_t *result);
void act_reboot(const char *line, const nn_result_t *result);
void act_shutdown(const char *line, const nn_result_t *result);
void act_fallback(const char *line, const nn_result_t *result);

#endif  /* AIOS_HW_HW_H_ */
