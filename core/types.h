#ifndef AIOS_CORE_TYPES_H_
#define AIOS_CORE_TYPES_H_

/* Freestanding integer types. No hosted headers are available in the kernel. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef signed char s8;
typedef signed short s16;
typedef signed int s32;
typedef signed long long s64;
typedef u32 size_t;

#define NULL ((void *)0)
#define PACKED __attribute__((packed))
#define STATIC_ASSERT(cond) typedef char static_assert_t##__LINE__[(cond) ? 1 : -1]
#define ARRAY_SIZE(array) ((size_t)(sizeof(array) / sizeof((array)[0])))
#define UNUSED(value) ((void)(value))

#endif  /* AIOS_CORE_TYPES_H_ */
