#pragma once
#include <stdint.h>

// Top-down sRGB RGBA. The square crop is 1.5 primary widths on each side,
// centered horizontally on the primary and starting 0.25 widths above its bottom.
enum { YSP_CARGO_PLATE_SIZE = 96 };
// Returns 30/31 (the suffix of DE:1052) or zero. On success, bounds contain
// x, y, width, height in crop pixels.
#ifdef __cplusplus
extern "C" {
#endif
int32_t ysp_german_cargo_plate(const uint8_t *rgba, double primary_width, int32_t *bounds);
#ifdef __cplusplus
}
#endif
