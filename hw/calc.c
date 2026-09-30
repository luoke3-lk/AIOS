/* Signed 32-bit, two-operand calculator for symbols and English operators. */
#include "hw/hw.h"

#include "core/string.h"
#include "drivers/vga.h"

static const char *skip_space(const char *cursor) {
    while (is_space(*cursor)) {
        ++cursor;
    }
    return cursor;
}

static int parse_integer(const char **cursor, s32 *value) {
    const char *text = skip_space(*cursor);
    u32 magnitude = 0u;
    u32 base = 10u;
    int negative = 0;
    int digits = 0;
    if (*text == '-') {
        negative = 1;
        ++text;
    } else if (*text == '+') {
        ++text;
    }
    if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        base = 16u;
        text += 2;
    }
    for (;;) {
        u32 digit = 0u;
        if (*text >= '0' && *text <= '9') {
            digit = (u32)(*text - '0');
        } else if (base == 16u && *text >= 'a' && *text <= 'f') {
            digit = 10u + (u32)(*text - 'a');
        } else if (base == 16u && *text >= 'A' && *text <= 'F') {
            digit = 10u + (u32)(*text - 'A');
        } else {
            break;
        }
        magnitude = magnitude * base + digit;
        ++text;
        digits = 1;
    }
    if (!digits) {
        return -1;
    }
    *value = negative ? -(s32)magnitude : (s32)magnitude;
    *cursor = text;
    return 0;
}

static const char *find_first_number(const char *line) {
    const char *cursor = line;
    while (*cursor != '\0') {
        if (is_digit(*cursor) || ((*cursor == '-' || *cursor == '+') && is_digit(cursor[1]))) {
            return cursor;
        }
        ++cursor;
    }
    return NULL;
}

static int text_has(const char *text, const char *word) {
    const size_t length = strlen(word);
    while (*text != '\0') {
        if (strncmp(text, word, length) == 0) {
            return 1;
        }
        ++text;
    }
    return 0;
}

void act_calc(const char *line, const nn_result_t *result) {
    const char *cursor = find_first_number(line);
    const char *between = NULL;
    s32 left = 0;
    s32 right = 0;
    s32 answer = 0;
    char operation = 0;
    char number[12];
    UNUSED(result);
    if (cursor == NULL || parse_integer(&cursor, &left) != 0) {
        vga_puts_attr("error: expected two integers\n", ATTR_ERR);
        return;
    }
    between = cursor;
    cursor = skip_space(cursor);
    if (*cursor == '+' || *cursor == '-' || *cursor == '*' || *cursor == '/') {
        operation = *cursor++;
    } else {
        while (*cursor != '\0' && !is_digit(*cursor) &&
               !((*cursor == '-' || *cursor == '+') && is_digit(cursor[1]))) {
            ++cursor;
        }
    }
    if (parse_integer(&cursor, &right) != 0) {
        vga_puts_attr("error: expected two integers\n", ATTR_ERR);
        return;
    }
    if (operation == 0) {
        if (text_has(between, "plus")) {
            operation = '+';
        } else if (text_has(between, "minus")) {
            operation = '-';
        } else if (text_has(between, "times") || text_has(between, "multiplied")) {
            operation = '*';
        } else if (text_has(between, "divide")) {
            operation = '/';
        }
    }
    if (operation == '+') {
        answer = left + right;
    } else if (operation == '-') {
        answer = left - right;
    } else if (operation == '*') {
        answer = left * right;
    } else if (operation == '/') {
        if (right == 0) {
            vga_puts_attr("error: divide by zero\n", ATTR_ERR);
            return;
        }
        answer = left / right;
    } else {
        vga_puts_attr("error: expected + - * or /\n", ATTR_ERR);
        return;
    }
    vga_puts_attr("result: ", ATTR_AI);
    vga_puts_attr(s32_to_dec(answer, number), ATTR_AI);
    vga_putc('\n');
}
