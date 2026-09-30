/* The single intent-to-action dispatch point for the entire kernel. */
#include "shell/dispatch.h"

const intent_entry_t INTENT_TABLE[INTENT_COUNT] = {
    {INTENT_CLEAR, "INTENT_CLEAR", "clear the screen", "clear the screen", act_clear},
    {INTENT_MEMINFO, "INTENT_MEMINFO", "e820 map and allocator", "tell me about my memory", act_meminfo},
    {INTENT_CPUINFO, "INTENT_CPUINFO", "cpuid vendor/brand", "what cpu is this", act_cpuinfo},
    {INTENT_SELFTEST, "INTENT_SELFTEST", "pci scan, mem march, rtc", "run a hardware self test", act_selftest},
    {INTENT_DISKINFO, "INTENT_DISKINFO", "ata identify", "is there a disk installed", act_diskinfo},
    {INTENT_MODELINFO, "INTENT_MODELINFO", "shape, bit width, rom", "what model are you using", act_modelinfo},
    {INTENT_CALC, "INTENT_CALC", "integer calculator", "what is 12 times 7", act_calc},
    {INTENT_SCREENTEST, "INTENT_SCREENTEST", "color and pattern test", "test the screen", act_screentest},
    {INTENT_HELP, "INTENT_HELP", "help", "help", act_help},
    {INTENT_ABOUT, "INTENT_ABOUT", "about", "who are you", act_about},
    {INTENT_REBOOT, "INTENT_REBOOT", "hardware reset", "reboot", act_reboot},
    {INTENT_SHUTDOWN, "INTENT_SHUTDOWN", "power off", "shutdown", act_shutdown},
    {INTENT_FALLBACK, "INTENT_FALLBACK", "unknown intent", "-", act_fallback},
};

void dispatch(u8 id, const char *line, const nn_result_t *result) {
    if (id >= INTENT_COUNT) {
        id = INTENT_FALLBACK;
    }
    INTENT_TABLE[id].fn(line, result);
}

const char *intent_name(u8 id) {
    if (id >= INTENT_COUNT) {
        id = INTENT_FALLBACK;
    }
    return INTENT_TABLE[id].name;
}
