#include "geodesk_adapter.h"
#include <geodesk/geodesk.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <limits>
#include <memory>
#include <vector>

namespace {
struct Reader {
    geodesk::Features library;
    geodesk::Features ways;
    geodesk::Features nodes;
    // GOQL's w selector excludes area ways. Closed residential/service squares
    // can be tagged as areas in OSM and are still canonical matcher candidates.
    // Include areas as well, then retain source type=way during iteration.
    explicit Reader(const char* path): library(path), ways(library("wa[highway]")), nodes(library("n")) {}
};
}

extern "C" void* storage_geodesk_open(const char* path, char* err, size_t err_len) {
    if (err && err_len) err[0] = 0;
    try {
        if (!path || !*path) throw std::invalid_argument("empty GOL path");
        return new Reader(path);
    } catch (const std::exception& e) {
        if (err && err_len) std::snprintf(err, err_len, "%s", e.what());
        return nullptr;
    }
}

static int candidates(void* handle, double min_lon, double min_lat,
    double max_lon, double max_lat, int64_t** ids, size_t* count, bool nodes) {
    if (!handle || !ids || !count) return -1;
    *ids = nullptr;
    *count = 0;
    if (!std::isfinite(min_lon) || !std::isfinite(min_lat) ||
        !std::isfinite(max_lon) || !std::isfinite(max_lat) ||
        min_lon > max_lon || min_lat > max_lat ||
        min_lon < -179.999 || max_lon > 179.999 ||
        min_lat < -85 || max_lat > 85) return -2;
    try {
        // GOL stores projected integer coordinates. Expand each axis by two
        // projected units (~19 mm at the equator) so projection rounding never
        // drops a canonical E7 bounding-box boundary hit. The caller must apply
        // the original source-precision box test after joining canonical rows.
        const auto box = geodesk::Box::ofWSEN(min_lon, min_lat, max_lon, max_lat);
        const geodesk::Box expanded(box.minX()-2, box.minY()-2,
            box.maxX()+2, box.maxY()+2);
        std::vector<int64_t> result;
        // Box operator explicitly tests FEATURE BOUNDS, not geometry
        // intersection. Query every highway value, including uncommon ones;
        // the canonical join selects the precise admitted source scope.
        const auto& features = nodes ? static_cast<Reader*>(handle)->nodes :
            static_cast<Reader*>(handle)->ways;
        for (geodesk::Feature feature: features(expanded)) {
            if (!nodes && !feature.isWay()) continue;
            result.push_back(feature.id());
        }
        std::sort(result.begin(), result.end());
        result.erase(std::unique(result.begin(), result.end()), result.end());
        if (!result.empty()) {
            *ids = static_cast<int64_t*>(std::malloc(result.size()*sizeof(int64_t)));
            if (!*ids) return -3;
            std::memcpy(*ids, result.data(), result.size()*sizeof(int64_t));
        }
        *count = result.size();
        return 0;
    } catch (...) {
        return -4;
    }
}

extern "C" int storage_geodesk_candidates(void* handle, double min_lon,
    double min_lat, double max_lon, double max_lat, int64_t** ids, size_t* count) {
    return candidates(handle, min_lon, min_lat, max_lon, max_lat, ids, count, false);
}

extern "C" int storage_geodesk_node_candidates(void* handle, double min_lon,
    double min_lat, double max_lon, double max_lat, int64_t** ids, size_t* count) {
    return candidates(handle, min_lon, min_lat, max_lon, max_lat, ids, count, true);
}


extern "C" void storage_geodesk_free_ids(int64_t* ids) { std::free(ids); }
extern "C" void storage_geodesk_close(void* handle) { delete static_cast<Reader*>(handle); }
