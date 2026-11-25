#include "german_cargo_plate.h"

#include <algorithm>
#include <array>
#include <cmath>

namespace {
constexpr int size = YSP_CARGO_PLATE_SIZE;
constexpr int columns = 16;
constexpr int rows = 12;

// Prototypes sampled from the two faces on page 18 of the official VzKat,
// Teil 7 (BMVBW-S32-0001-KF10-BS-A007.pdf). Dots omit mixed and border cells.
// Paper, dark ink, orange cargo, and blue wave ink are scored separately.
constexpr const char *faces[][rows] = {
    {
        "................", ".WWWW......WWWW.", ".WWWWDOOOOD.WWW.",
        ".WWWWDOOOOO.WWW.", ".WWWWDOOOOO.WWW.", ".WWWWDOOOOO.WWW.",
        ".WWWWDOOOOO.WWW.", ".WWW.DDDDDD.WWW.", ".WWW.DD...D.WWW.",
        ".WWW.DD.DDD.WWW.", ".WWWW..WW..WWWW.", "................",
    }, {
        "................", ".WWWWWW...WWWWW.", ".WWWW.OOOO.WWWW.",
        ".WWWWOOOOOO.WWW.", ".WWWWOOOOOO.WWW.", ".WWWWDOOOOD.WWW.",
        ".WWWWDD..DD.WWW.", ".WWWWDD..DD.WWW.", ".WWWW..W...WWWW.",
        ".WWWWBBBBBBBWWW.", ".WWWWWBBBBBWWWW.", "................",
    },
};

struct Color {
    double luma, redGreen, redBlue;
};

Color pixel(const uint8_t *rgba, int x, int y) {
    const uint8_t *p = rgba + 4 * (y * size + x);
    return {(p[0] + 2.0 * p[1] + p[2]) / 4.0, double(p[0]) - p[1], double(p[0]) - p[2]};
}

double unit(double value) { return std::clamp(value, 0.0, 1.0); }

double match(const uint8_t *rgba, int x, int y, int width, int height, int face) {
    const auto sample = [&](int column, int row) {
        return pixel(rgba, x + (2 * column + 1) * width / (2 * columns),
                     y + (2 * row + 1) * height / (2 * rows));
    };
    const Color core = sample(8, 4);
    if (core.redGreen < 8 || core.redBlue < 5) return 0;
    // Normalize against the same plate's paper, including exposure and cast.
    Color paper{};
    std::array<double, 2> sides{};
    for (int row : {2, 5, 8, 10}) {
        for (int side = 0; side < 2; ++side) {
            const Color p = sample(side == 0 ? 3 : 12, row);
            paper.luma += p.luma / 8;
            paper.redGreen += p.redGreen / 8;
            paper.redBlue += p.redBlue / 8;
            sides[side] += p.luma / 4;
        }
    }
    if (paper.luma < 62 || std::abs(sides[0] - sides[1]) > paper.luma * 0.25 ||
        std::abs(paper.redBlue) > paper.luma * 0.38) return 0;
    // Constrain the match to the full plate. Fitting a shorter box around
    // just the tank and axle can otherwise make the oval resemble a rectangle.
    double edge = 0;
    for (int row : {3, 6, 9}) {
        const int at = y + (2 * row + 1) * height / (2 * rows);
        edge += unit((sample(3, row).luma - pixel(rgba, x, at).luma) / (0.40 * paper.luma));
        edge += unit((sample(12, row).luma - pixel(rgba, x + width - 1, at).luma) / (0.40 * paper.luma));
    }
    for (int col : {3, 12}) {
        const int at = x + (2 * col + 1) * width / (2 * columns);
        edge += unit((sample(col, 10).luma - pixel(rgba, at, y + height - 1).luma) / (0.40 * paper.luma));
    }
    edge /= 8;
    if (edge < 0.25) return 0;
    double white = 0, orange = 0, ink = 0, waves = 0;
    int whiteCount = 0, orangeCount = 0, inkCount = 0, wavesCount = 0;
    for (int row = 1; row < rows - 1; ++row) {
        for (int col = 1; col < columns - 1; ++col) {
            const char cell = faces[face][row][col];
            if (cell == '.') continue;
            const Color p = sample(col, row);
            const double level = p.luma / paper.luma;
            const double warmth = std::min(p.redGreen - paper.redGreen, p.redBlue - paper.redBlue) / paper.luma;
            switch (cell) {
            case 'W': white += unit((level - 0.71) / 0.25) * unit(1.2 - 3.0 * std::abs(warmth)); ++whiteCount; break;
            case 'O': orange += unit((warmth - 0.055) / 0.19); ++orangeCount; break;
            case 'D':
                // The orange load cannot also satisfy the black chassis mask.
                ink += unit((0.83 - level) / 0.43)
                    * (p.redGreen > 11 && p.redBlue > 11 ? unit(1.35 - 6.0 * warmth) : 1.0);
                ++inkCount;
                break;
            // Waves are narrow in the source. At dashcam resolution their
            // darker troughs can retain more structure than their blue hue.
            case 'B': waves += unit((0.96 - level) / 0.32 - 1.5 * warmth); ++wavesCount; break;
            }
        }
    }
    white /= whiteCount;
    orange /= orangeCount;
    ink /= inkCount;
    if (white < 0.76 || orange < 0.62 || ink < 0.51) return 0;
    if (wavesCount) {
        waves /= wavesCount;
        if (waves < 0.28) return 0;
    }
    const double graphic = (white + orange + ink + (wavesCount ? 0.5 * waves : 0)) / (wavesCount ? 3.5 : 3.0);
    return 0.75 * graphic + 0.25 * edge;
}
}  // namespace

int32_t ysp_german_cargo_plate(const uint8_t *rgba, double primary_width, int32_t *bounds) {
    if (!rgba || !bounds || !std::isfinite(primary_width) || primary_width < 24) return 0;
    std::array<double, 2> best{};
    std::array<std::array<int32_t, 4>, 2> boxes{};
    for (int width : {44, 49, 54, 59, 64, 69, 74, 79}) {
        for (int height : {width * 65 / 100, width * 75 / 100, width * 85 / 100}) {
            for (int center : {39, 42, 45, 48, 51, 54, 57}) {
                const int left = center - width / 2;
                if (left < 0 || left + width > size) continue;
                for (int top : {6, 9, 12, 15, 18, 21, 24, 27, 30}) {
                    if (top + height > size) continue;
                    for (int face = 0; face < 2; ++face) {
                        const double score = match(rgba, left, top, width, height, face);
                        if (score <= best[face]) continue;
                        best[face] = score;
                        boxes[face] = {left, top, width, height};
                    }
                }
            }
        }
    }
    const int face = best[1] > best[0] ? 1 : 0;
    if (best[face] < 0.67 || best[face] - best[1 - face] < 0.018) return 0;
    std::copy(boxes[face].begin(), boxes[face].end(), bounds);
    return 30 + face;
}
