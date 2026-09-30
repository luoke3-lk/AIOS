#ifndef AIOS_CORE_STRING_H_
#define AIOS_CORE_STRING_H_

#include "core/types.h"

void *memcpy(void *destination, const void *source, size_t count);
void *memset(void *destination, int value, size_t count);
void *memmove(void *destination, const void *source, size_t count);
int memcmp(const void *left, const void *right, size_t count);
size_t strlen(const char *text);
int strcmp(const char *left, const char *right);
int strncmp(const char *left, const char *right, size_t count);
char *strcpy(char *destination, const char *source);
char *strncpy(char *destination, const char *source, size_t count);
char *strchr(const char *text, int character);
char to_lower(char character);
int is_digit(char character);
int is_space(char character);
char *u32_to_dec(u32 value, char buffer[11]);
char *s32_to_dec(s32 value, char buffer[12]);
char *u32_to_hex(u32 value, char buffer[11]);
char *u64_to_hex(u64 value, char buffer[19]);

#endif  /* AIOS_CORE_STRING_H_ */
