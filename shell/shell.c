/*
 * Single-threaded terminal shell. Keyboard decoding, line editing, NLU/NN,
 * metadata display, and VTable dispatch form one deterministic request path.
 */
#include "shell/shell.h"

#include "core/string.h"
#include "drivers/kbd.h"
#include "drivers/vga.h"
#include "hw/hw.h"
#include "shell/dispatch.h"
#include "shell/intent.h"

#if defined(__has_include)
#if __has_include("nn/config.h") && __has_include("nn/model_weights.h") && \
    __has_include("nn/nn.h") && __has_include("nlu/nlu.h")
#define AIOS_HAVE_MODEL 1
#include "nn/config.h"
#include "nn/nn.h"
#include "nlu/nlu.h"
#endif
#endif

#ifndef AIOS_HAVE_MODEL
#define AIOS_HAVE_MODEL 0
#define NLU_DIM 64
#define NN_CLASSES 12
#endif

#ifndef CONF_THRESHOLD
#define CONF_THRESHOLD 35u
#endif

static line_t g_line;

static int contains_text(const char *text, const char *needle) {
    size_t index = 0u;
    const size_t wanted = strlen(needle);
    if (wanted == 0u) {
        return 1;
    }
    while (text[index] != '\0') {
        if (strncmp(text + index, needle, wanted) == 0) {
            return 1;
        }
        ++index;
    }
    return 0;
}

static u8 fallback_classify(const char *line) {
    if (contains_text(line, "clear") || contains_text(line, "wipe") || contains_text(line, "cls")) {
        return INTENT_CLEAR;
    }
    if (contains_text(line, "memory") || contains_text(line, " ram")) {
        return INTENT_MEMINFO;
    }
    if (contains_text(line, "cpu") || contains_text(line, "processor") || contains_text(line, "chip")) {
        return INTENT_CPUINFO;
    }
    if (contains_text(line, "self test") || contains_text(line, "hardware") || contains_text(line, "pci")) {
        return INTENT_SELFTEST;
    }
    if (contains_text(line, "disk") || contains_text(line, "drive") || contains_text(line, "storage")) {
        return INTENT_DISKINFO;
    }
    if (contains_text(line, "model") || contains_text(line, "neural")) {
        return INTENT_MODELINFO;
    }
    if (contains_text(line, "calculate") || contains_text(line, "compute") ||
        contains_text(line, " plus ") || contains_text(line, " times ") ||
        contains_text(line, " minus ") || contains_text(line, " divided ")) {
        return INTENT_CALC;
    }
    if (contains_text(line, "screen") || contains_text(line, "display") || contains_text(line, "color")) {
        return INTENT_SCREENTEST;
    }
    if (contains_text(line, "help") || contains_text(line, "what can you do")) {
        return INTENT_HELP;
    }
    if (contains_text(line, "about") || contains_text(line, "who are you") || contains_text(line, "version")) {
        return INTENT_ABOUT;
    }
    if (contains_text(line, "reboot") || contains_text(line, "restart")) {
        return INTENT_REBOOT;
    }
    if (contains_text(line, "shutdown") || contains_text(line, "power off") || contains_text(line, "poweroff")) {
        return INTENT_SHUTDOWN;
    }
    return INTENT_FALLBACK;
}

static void infer(const char *line, nn_result_t *result) {
    u32 index = 0u;
    for (index = 0u; index < AIOS_NN_CLASSES; ++index) {
        result->logits[index] = 0;
    }
#if AIOS_HAVE_MODEL
    {
        s8 features[NLU_DIM];
        u8 top_ids[3] = {0u, 0u, 0u};
        u8 top_pct[3] = {0u, 0u, 0u};
        nlu_extract(line, features);
        nn_forward(features, result->logits);
        nn_softmax_top3(result->logits, top_ids, top_pct);
        for (index = 0u; index < 3u; ++index) {
            result->top3_id[index] = top_ids[index];
            result->top3_pct[index] = top_pct[index];
        }
        result->top1 = top_ids[0];
    }
#else
    result->top1 = fallback_classify(line);
    result->top3_id[0] = result->top1 < AIOS_NN_CLASSES ? result->top1 : INTENT_HELP;
    result->top3_id[1] = INTENT_HELP;
    result->top3_id[2] = INTENT_ABOUT;
    result->top3_pct[0] = result->top1 == INTENT_FALLBACK ? 20u : 95u;
    result->top3_pct[1] = 3u;
    result->top3_pct[2] = 2u;
#endif
}

static void print_percent(u8 percent) {
    char number[11];
    vga_puts(u32_to_dec(percent, number));
    vga_puts("%)\n");
}

static void print_top3(const nn_result_t *result) {
    u32 rank = 0u;
    for (rank = 0u; rank < 3u; ++rank) {
        vga_puts_attr(rank == 0u ? "AI: " : ".. ", ATTR_META);
        vga_puts_attr(intent_name(result->top3_id[rank]), ATTR_META);
        vga_puts_attr(" (", ATTR_META);
        vga_set_attr(ATTR_META);
        print_percent(result->top3_pct[rank]);
        vga_set_attr(ATTR_DEFAULT);
    }
}

void shell_prompt(void) {
#if PROMPT_STYLE == 0
    vga_puts_attr("AIOS> ", ATTR_PROMPT);
#else
    vga_puts_attr("{AIOS}> ", ATTR_PROMPT);
#endif
    vga_set_attr(ATTR_INPUT);
}

void shell_process_line(const char *line) {
    nn_result_t result;
    u8 selected = INTENT_FALLBACK;
    infer(line, &result);
    print_top3(&result);
    selected = result.top1;
    if (result.top3_pct[0] < CONF_THRESHOLD) {
        selected = INTENT_FALLBACK;
    }
    dispatch(selected, line, &result);
}

void shell_run(void) {
    line_init(&g_line, 8u);
    shell_prompt();
    for (;;) {
        char character = 0;
        u8 raw = 0u;
        if (!kbd_poll_key(&character, &raw)) {
            kbd_idle();
            continue;
        }
        if (character == '\n') {
            vga_putc('\n');
            if (g_line.len != 0u) {
                shell_process_line(g_line.buf);
                vga_putc('\n');
            }
            line_init(&g_line, 8u);
            shell_prompt();
        } else if (character == '\b') {
            if (line_backspace(&g_line)) {
                vga_putc('\b');
            }
        } else if (character >= 0x20 && character <= 0x7E) {
            if (line_feed(&g_line, character) == 0) {
                vga_putc(character);
            }
        }
    }
}
