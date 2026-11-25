#pragma once

#include <stdint.h>

#define YSP_TOWN_EXIT_WIDTH 96
#define YSP_TOWN_EXIT_HEIGHT 72

#ifdef __cplusplus
extern "C" {
#endif

// Input is a tightly packed top-down RGBA sample of the unpadded sign box.
// A positive result may support only a German city:end proposal with classifier score >= .45.
// Exit-only detector bands may use a negative result and a negative original face check to skip classification.
int32_t ysp_german_town_exit_rescue(const uint8_t *rgba);

#ifdef __cplusplus
}
#endif
