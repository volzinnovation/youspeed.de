#include "german_town_sign_face.h"

#include <algorithm>
#include <array>
#include <cmath>

namespace {
constexpr int W = YSP_TOWN_FACE_WIDTH, H = YSP_TOWN_FACE_HEIGHT;
enum Tone : uint8_t { Other, Yellow, Ink, White, Red };

// Reject marks too large to be individual letters, and arrowheads attached
// to a narrower vertical shaft. Work inside the panel, excluding its frame.
bool hasDirectionMark(std::array<Tone, W * H> pixels, int l, int t, int r, int b) {
    const int w = r - l, h = b - t;
    std::array<int, W * H> queue{};
    for (int y = t; y < b; ++y) for (int x = l; x < r; ++x) {
        if (pixels[y * W + x] != Ink) continue;
        int n = 1, minX = x, maxX = x, minY = y, maxY = y;
        std::array<int, H> rowLeft, rowRight;
        std::array<int, W> colTop, colBottom;
        rowLeft.fill(W);
        rowRight.fill(-1);
        colTop.fill(H);
        colBottom.fill(-1);
        queue[0] = y * W + x;
        pixels[queue[0]] = Other;
        for (int j = 0; j < n; ++j) {
            const int cx = queue[j] % W, cy = queue[j] / W;
            minX = std::min(minX, cx); maxX = std::max(maxX, cx);
            minY = std::min(minY, cy); maxY = std::max(maxY, cy);
            rowLeft[cy] = std::min(rowLeft[cy], cx);
            rowRight[cy] = std::max(rowRight[cy], cx);
            colTop[cx] = std::min(colTop[cx], cy);
            colBottom[cx] = std::max(colBottom[cx], cy);
            for (int ny = std::max(t, cy - 1); ny <= std::min(b - 1, cy + 1); ++ny)
                for (int nx = std::max(l, cx - 1); nx <= std::min(r - 1, cx + 1); ++nx) {
                    const int i = ny * W + nx;
                    if (pixels[i] == Ink) {
                        pixels[i] = Other;
                        queue[n++] = i;
                    }
                }
        }
        const int cw = maxX - minX + 1, ch = maxY - minY + 1;
        if (n * 1000 < w * h * 7) continue;
        // A junction diagram can have multiple arrowheads and no narrow
        // tail. Its connected ink spans both axes much farther than a glyph.
        if (cw * 100 >= w * 32 && ch * 100 >= h * 31 && n * 100 >= cw * ch * 11) return true;
        // Look for the thick head and narrow shaft in either orientation.
        // A long connected outline or joined text is not by itself an arrow.
        for (bool horizontal : {false, true}) {
            const int length = horizontal ? cw : ch, breadth = horizontal ? ch : cw;
            if (length * 100 < (horizontal ? w * 22 : h * 29)
                || breadth * 100 < (horizontal ? h * 12 : w * 10)) continue;
            for (bool forward : {false, true}) {
                const auto span = [&](int k) {
                    const int axis = forward ? k : length - 1 - k;
                    if (horizontal) return colBottom[minX + axis] - colTop[minX + axis] + 1;
                    return rowRight[minY + axis] - rowLeft[minY + axis] + 1;
                };
                const int tip = std::max(span(0), span(1));
                int head = 0;
                for (int k = 1; k <= length / 2; ++k) head = std::max(head, span(k));
                const int shaft = std::max({span(length * 2 / 3), span(length * 3 / 4), span(length - 2)});
                if (head >= breadth * 0.8 && tip <= head * 0.65 && shaft <= head * (horizontal ? 0.66 : 0.54)) return true;
            }
        }
    }
    return false;
}

// A small white inset (such as the yield symbol on the Eyachbrücke
// direction board) can survive even when a proposal clips the diagram.
// Require a compact patch inside the yellow panel so isolated reflections
// or pale pixels on the outside of the box do not count.
bool hasPaleInset(const uint8_t *rgba, int l, int t, int r, int b) {
    std::array<uint8_t, W * H> pale{};
    for (int y = t; y < b; ++y) for (int x = l; x < r; ++x) {
        const auto *p = rgba + 4 * (y * W + x);
        const int high = std::max({p[0], p[1], p[2]});
        const int low = std::min({p[0], p[1], p[2]});
        pale[y * W + x] = low >= 145 && high - low <= 46 && std::abs(int(p[1]) - p[2]) <= 32;
    }
    for (int y = t + 1; y < b - 1; ++y) for (int x = l + 1; x < r - 1; ++x) {
        if (!pale[y * W + x]) continue;
        int support = 0;
        for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
            support += pale[(y + dy) * W + x + dx];
        }
        if (support >= 8) return true;
    }
    return false;
}
}

int32_t ysp_german_town_sign_face(const uint8_t *rgba, double width, double height, int32_t town_exit) {
    if (!rgba || !std::isfinite(width) || !std::isfinite(height) || width < 24 || height < 16
        || width < 0.94 * height || width > 2.35 * height) return 0;

    std::array<Tone, W * H> tones{};
    std::array<int, W> columns{};
    std::array<int, H> rows{};
    int yellow = 0, yellowGreen = 0, yellowRed = 0;
    for (int y = 0; y < H; ++y) for (int x = 0; x < W; ++x) {
        const auto *p = rgba + 4 * (y * W + x);
        const int r = p[0], g = p[1], b = p[2];
        // Ochre/yellow under camera exposure changes; pale yellow and
        // near-neutral reflections are not evidence for a yellow face.
        if (r >= 65 && g >= 48 && r * 100 >= g * 95 && g * 100 >= r * 55
            && g - b >= 12 && (r - b) * 100 >= r * 19) {
            tones[y * W + x] = Yellow;
            ++columns[x]; ++rows[y]; ++yellow;
            yellowGreen += g; yellowRed += r;
        }
    }
    if (yellow * 100 < W * H * 38) return 0;

    // Bound the panel using substantial yellow support. This ignores small
    // amounts of scene background at the edges of the proposal.
    int l = 0, t = 0, r = W, b = H;
    while (l < W && columns[l] < H / 4) ++l;
    while (r > l && columns[r - 1] < H / 4) --r;
    while (t < H && rows[t] < W / 4) ++t;
    while (b > t && rows[b - 1] < W / 4) --b;
    const int w = r - l, h = b - t;
    if (w < W * 0.68 || h < H * (town_exit ? 0.58 : 0.62) || width * w * H < 0.94 * height * h * W
        || width * w * H > 2.30 * height * h * W) return 0;

    // Verify coverage at all four corners as well as in the middle. A
    // chevron-shaped panel can meet the overall color and aspect checks.
    int corners = 0;
    for (int sideY : {0, 1}) for (int sideX : {0, 1}) {
        int support = 0, area = 0;
        for (int y = h / 12; y < h / 4; ++y) for (int x = w / 12; x < w / 4; ++x) {
            support += tones[(sideY ? b - 1 - y : t + y) * W + (sideX ? r - 1 - x : l + x)] == Yellow;
            ++area;
        }
        corners += support * 100 >= area * 40;
    }

    if (corners < 3) return 0;

    // Perspective can slope a rectangular edge, but it cannot make the
    // middle of the edge project past both ends like a direction board.
    for (bool left : {false, true}) {
        const auto edge = [&](int start, int end) {
            std::array<int, H> positions{};
            int n = 0;
            for (int y = t + h * start / 100; y < t + h * end / 100; ++y) {
                for (int i = 0; i + 2 < w; ++i) {
                    const int x = left ? l + i : r - 1 - i, step = left ? 1 : -1;
                    if (tones[y * W + x] == Yellow && tones[y * W + x + step] == Yellow
                        && tones[y * W + x + 2 * step] == Yellow) {
                        positions[n++] = i;
                        break;
                    }
                }
            }
            if (n < 3) return -1;
            std::sort(positions.begin(), positions.begin() + n);
            return positions[n / 2];
        };
        const int top = edge(12, 28), middle = edge(42, 58), bottom = edge(72, 88);
        if (top >= 0 && middle >= 0 && bottom >= 0
            && (top + bottom - 2 * middle) * 100 > w * 16) return 0;
    }

    const int inkLimit = yellowGreen / yellow * 83 / 100;
    const int greenToRed = 100 * yellowGreen / yellowRed;
    for (int i = 0; i < W * H; ++i) {
        const int red = rgba[4*i], green = rgba[4*i + 1], blue = rgba[4*i + 2];
        const int high = std::max({red, green, blue}), low = std::min({red, green, blue});
        if (red >= 53 && red - green >= 15 && red - blue >= 16 && green * 100 <= red * std::min(81, greenToRed - 12))
            tones[i] = Red;
        else if (low >= 162 && high - low <= 27)
            tones[i] = White;
        else if (green <= inkLimit && high <= inkLimit + 42 && high - low <= 78)
            tones[i] = Ink;
    }

    // A dark frame near the outside of the yellow face separates town
    // panels from yellow objects and loose text. Allow perspective, faded
    // edges and boxes that clip the frame on one side.
    int supportedEdges = 0;
    for (int side = 0; side < 4; ++side) {
        const bool horizontal = side < 2;
        const int span = horizontal ? w : h;
        int support = 0;
        for (int i = span / 5; i < span - span / 5; ++i) {
            bool dark = false;
            for (int d = -4; d <= 5; ++d) {
                const int x = horizontal ? l + i : side == 2 ? l + d : r - 1 - d;
                const int y = !horizontal ? t + i : side == 0 ? t + d : b - 1 - d;
                if (x >= 0 && x < W && y >= 0 && y < H) dark |= tones[y * W + x] == Ink;
            }
            support += dark;
        }
        supportedEdges += support * 100 >= 39 * (span - 2 * (span / 5));
    }
    if (supportedEdges < 1 && (w < W * 0.78 || h < H * 0.75 || corners < 4)) return 0;

    const int insetX = std::max(3, w / 11), insetY = std::max(3, h / 11);
    const int il = l + insetX, ir = r - insetX, it = t + insetY, ib = b - insetY;
    const int area = (ir - il) * (ib - it);
    int ink = 0, white = 0, red = 0, strongRed = 0, face = 0;
    for (int y = it; y < ib; ++y) for (int x = il; x < ir; ++x) {
        const int i = y * W + x;
        const Tone tone = tones[i];
        ink += tone == Ink; white += tone == White; red += tone == Red; face += tone == Yellow;
        strongRed += tone == Red && rgba[4*i + 1] * 100 <= rgba[4*i] * 64
            && rgba[4*i + 1] <= rgba[4*i + 2] + 18;
    }
    if (white * 100 > area * 3 || ink * 1000 < area * 7 || face * 100 < area * 40
        || (ink + face + red) * 100 < area * 68) return 0;
    int whiteInCrop = 0;
    for (int y = H / 10; y < H - H / 10; ++y)
        for (int x = W / 10; x < W - W / 10; ++x) whiteInCrop += tones[y * W + x] == White;
    if (whiteInCrop * 100 > (W - 2 * (W / 10)) * (H - 2 * (H / 10)) * 5) return 0;
    if (!town_exit) {
        if (strongRed * 100 > area * 3 || hasPaleInset(rgba, il, it, ir, ib)) return 0;
        // Use the dark core of the markings for arrow geometry so blurred
        // shadows joining neighboring letters do not form a single symbol.
        for (int y = it; y < ib; ++y) for (int x = il; x < ir; ++x) {
            const int i = y * W + x;
            if (tones[i] == Ink && rgba[4*i + 1] * 100 > inkLimit * 90) tones[i] = Other;
        }
        return !hasDirectionMark(tones, il, it, ir, ib);
    }

    // Genuine 311 can have an up arrow above the crossed-out town name.
    // Require the red rising strike, spread across the panel rather than
    // a red logo or a single red patch; never use the arrow as exit proof.
    if (red * 100 < area * 2) return 0;
    int n = 0, sx = 0, sy = 0, sxx = 0, sxy = 0, syy = 0;
    for (int x = il; x < ir; ++x) {
        int count = 0, sum = 0;
        for (int y = it; y < ib; ++y) if (tones[y * W + x] == Red) {
            ++count; sum += y;
        }
        if (count == 0) continue;
        const int y = sum / count;
        ++n; sx += x; sy += y; sxx += x*x; sxy += x*y; syy += y*y;
    }
    if (n * 100 < (ir - il) * 39) return 0;
    const double covariance = double(n) * sxy - sx * sy;
    const double xVariance = double(n) * sxx - sx * sx;
    const double yVariance = double(n) * syy - sy * sy;
    return covariance < -0.20 * xVariance && covariance > -1.40 * xVariance
        && covariance * covariance >= 0.70 * xVariance * yVariance;
}
