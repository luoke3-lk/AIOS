/*
 * Tiny freestanding string and integer formatting routines.
 * These functions intentionally use no compiler builtins or hosted headers.
 */
#include "core/string.h"

void *memcpy(void *destination, const void *source, size_t count) {
    u8 *dst = (u8 *)destination;
    const u8 *src = (const u8 *)source;
    size_t index = 0u;
    for (index = 0u; index < count; ++index) {
        dst[index] = src[index];
    }
    return destination;
}

void *memset(void *destination, int value, size_t count) {
    u8 *dst = (u8 *)destination;
    size_t index = 0u;
    for (index = 0u; index < count; ++index) {
        dst[index] = (u8)value;
    }
    return destination;
}

void *memmove(void *destination, const void *source, size_t count) {
    u8 *dst = (u8 *)destination;
    const u8 *src = (const u8 *)source;
    size_t index = 0u;
    if (dst == src || count == 0u) {
        return destination;
    }
    if (dst < src) {
        for (index = 0u; index < count; ++index) {
            dst[index] = src[index];
        }
    } else {
        index = count;
        while (index > 0u) {
            --index;
            dst[index] = src[index];
        }
    }
    return destination;
}

int memcmp(const void *left, const void *right, size_t count) {
    const u8 *lhs = (const u8 *)left;
    const u8 *rhs = (const u8 *)right;
    size_t index = 0u;
    for (index = 0u; index < count; ++index) {
        if (lhs[index] != rhs[index]) {
            return (int)lhs[index] - (int)rhs[index];
        }
    }
    return 0;
}

size_t strlen(const char *text) {
    size_t length = 0u;
    while (text[length] != '\0') {
        ++length;
    }
    return length;
}

int strcmp(const char *left, const char *right) {
    size_t index = 0u;
    while (left[index] != '\0' && left[index] == right[index]) {
        ++index;
    }
    return (int)(u8)left[index] - (int)(u8)right[index];
}

int strncmp(const char *left, const char *right, size_t count) {
    size_t index = 0u;
    for (index = 0u; index < count; ++index) {
        const u8 lhs = (u8)left[index];
        const u8 rhs = (u8)right[index];
        if (lhs != rhs || lhs == 0u || rhs == 0u) {
            return (int)lhs - (int)rhs;
        }
    }
    return 0;
}

char *strcpy(char *destination, const char *source) {
    size_t index = 0u;
    do {
        destination[index] = source[index];
    } while (source[index++] != '\0');
    return destination;
}

char *strncpy(char *destination, const char *source, size_t count) {
    size_t index = 0u;
    while (index < count && source[index] != '\0') {
        destination[index] = source[index];
        ++index;
    }
    while (index < count) {
        destination[index++] = '\0';
    }
    return destination;
}

char *strchr(const char *text, int character) {
    const char wanted = (char)character;
    while (*text != '\0') {
        if (*text == wanted) {
            return (char *)text;
        }
        ++text;
    }
    return wanted == '\0' ? (char *)text : NULL;
}

char to_lower(char character) {
    if (character >= 'A' && character <= 'Z') {
        return (char)(character + ('a' - 'A'));
    }
    return character;
}

int is_digit(char character) {
    return character >= '0' && character <= '9';
}

int is_space(char character) {
    return character == ' ' || character == '\t' || character == '\r' || character == '\n';
}

char *u32_to_dec(u32 value, char buffer[11]) {
    char reverse[10];
    size_t length = 0u;
    size_t index = 0u;
    if (value == 0u) {
        buffer[0] = '0';
        buffer[1] = '\0';
        return buffer;
    }
    while (value != 0u) {
        reverse[length++] = (char)('0' + (value % 10u));
        value /= 10u;
    }
    for (index = 0u; index < length; ++index) {
        buffer[index] = reverse[length - index - 1u];
    }
    buffer[length] = '\0';
    return buffer;
}

char *s32_to_dec(s32 value, char buffer[12]) {
    u32 magnitude = 0u;
    if (value < 0) {
        buffer[0] = '-';
        magnitude = (u32)(-(value + 1)) + 1u;
        u32_to_dec(magnitude, buffer + 1);
    } else {
        u32_to_dec((u32)value, buffer);
    }
    return buffer;
}

static char hex_digit(u8 value) {
    return value < 10u ? (char)('0' + value) : (char)('A' + value - 10u);
}

char *u32_to_hex(u32 value, char buffer[11]) {
    s32 shift = 28;
    size_t out = 0u;
    int started = 0;
    buffer[out++] = '0';
    buffer[out++] = 'x';
    while (shift >= 0) {
        const u8 digit = (u8)((value >> (u32)shift) & 0x0Fu);
        if (digit != 0u || started || shift == 0) {
            buffer[out++] = hex_digit(digit);
            started = 1;
        }
        shift -= 4;
    }
    buffer[out] = '\0';
    return buffer;
}

char *u64_to_hex(u64 value, char buffer[19]) {
    union {
        u64 whole;
        u32 half[2];
    } split;
    char high[11];
    char low[11];
    size_t out = 0u;
    size_t index = 0u;
    split.whole = value;
    u32_to_hex(split.half[1], high);
    u32_to_hex(split.half[0], low);
    buffer[out++] = '0';
    buffer[out++] = 'x';
    if (split.half[1] != 0u) {
        for (index = 2u; high[index] != '\0'; ++index) {
            buffer[out++] = high[index];
        }
        for (index = strlen(low) - 2u; index < 8u; ++index) {
            buffer[out++] = '0';
        }
        for (index = 2u; low[index] != '\0'; ++index) {
            buffer[out++] = low[index];
        }
    } else {
        for (index = 2u; low[index] != '\0'; ++index) {
            buffer[out++] = low[index];
        }
    }
    buffer[out] = '\0';
    return buffer;
}
