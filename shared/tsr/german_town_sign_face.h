#pragma once

#include <stdint.h>

#define YSP_TOWN_FACE_WIDTH 80
#define YSP_TOWN_FACE_HEIGHT 64

#ifdef __cplusplus
extern "C" {
#endif
// Top-down sRGB RGBX/RGBA, tightly sampled from the detector box without
// classifier padding. Dimensions describe the original box in source pixels.
int32_t ysp_german_town_sign_face(const uint8_t *rgba, double width, double height, int32_t town_exit);
#ifdef __cplusplus
}
#endif
