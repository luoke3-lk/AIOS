/* Compiler runtime helpers used by some 32-bit code-generation paths. */
#include "core/types.h"

u32 __udivsi3(u32 numerator, u32 denominator) {
    u32 quotient = 0u;
    u32 remainder = 0u;
    s32 bit = 31;
    if (denominator == 0u) {
        return 0u;
    }
    for (bit = 31; bit >= 0; --bit) {
        remainder = (remainder << 1u) | ((numerator >> (u32)bit) & 1u);
        if (remainder >= denominator) {
            remainder -= denominator;
            quotient |= 1u << (u32)bit;
        }
    }
    return quotient;
}

u32 __umodsi3(u32 numerator, u32 denominator) {
    u32 remainder = 0u;
    s32 bit = 31;
    if (denominator == 0u) {
        return 0u;
    }
    for (bit = 31; bit >= 0; --bit) {
        remainder = (remainder << 1u) | ((numerator >> (u32)bit) & 1u);
        if (remainder >= denominator) {
            remainder -= denominator;
        }
    }
    return remainder;
}

s32 __divsi3(s32 numerator, s32 denominator) {
    const int negative = (numerator < 0) != (denominator < 0);
    const u32 lhs = numerator < 0 ? (u32)(-(numerator + 1)) + 1u : (u32)numerator;
    const u32 rhs = denominator < 0 ? (u32)(-(denominator + 1)) + 1u : (u32)denominator;
    const u32 quotient = __udivsi3(lhs, rhs);
    return negative ? -(s32)quotient : (s32)quotient;
}

s32 __modsi3(s32 numerator, s32 denominator) {
    const u32 lhs = numerator < 0 ? (u32)(-(numerator + 1)) + 1u : (u32)numerator;
    const u32 rhs = denominator < 0 ? (u32)(-(denominator + 1)) + 1u : (u32)denominator;
    const u32 remainder = __umodsi3(lhs, rhs);
    return numerator < 0 ? -(s32)remainder : (s32)remainder;
}
