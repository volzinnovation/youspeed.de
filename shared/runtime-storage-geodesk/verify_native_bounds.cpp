// Host-only evidence check. Not linked into the phone adapter.
#include <geodesk/geodesk.h>
#include <sqlite3.h>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <unordered_map>

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: verify_native_bounds SOURCE.sqlite REGION.gol\n";
        return 2;
    }
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(argv[1], &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK)
        throw std::runtime_error("cannot open canonical source");
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db,
        "SELECT way_id,min_lon,min_lat,max_lon,max_lat FROM ways", -1,
        &stmt, nullptr) != SQLITE_OK) throw std::runtime_error(sqlite3_errmsg(db));
    std::unordered_map<int64_t,geodesk::Box> source;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        source.emplace(sqlite3_column_int64(stmt, 0), geodesk::Box::ofWSEN(
            sqlite3_column_double(stmt, 1), sqlite3_column_double(stmt, 2),
            sqlite3_column_double(stmt, 3), sqlite3_column_double(stmt, 4)));
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);
    geodesk::Features library(argv[2]);
    uint64_t checked = 0, nonzero = 0;
    int64_t max_abs_units = 0;
    for (geodesk::Feature feature: library("wa[highway]")) {
        if (!feature.isWay()) continue;
        auto it = source.find(feature.id());
        if (it == source.end()) continue;
        auto actual = feature.bounds();
        auto expected = it->second;
        int64_t delta = std::max({
            std::abs(int64_t(actual.minX())-expected.minX()),
            std::abs(int64_t(actual.minY())-expected.minY()),
            std::abs(int64_t(actual.maxX())-expected.maxX()),
            std::abs(int64_t(actual.maxY())-expected.maxY())});
        max_abs_units = std::max(max_abs_units, delta);
        if (delta) ++nonzero;
        ++checked;
        source.erase(it);
    }
    std::cout << "{\"checked_source_ways\":" << checked
        << ",\"missing_source_ways\":" << source.size()
        << ",\"ways_with_nonzero_projected_bounds_delta\":" << nonzero
        << ",\"maximum_absolute_projected_units_delta\":" << max_abs_units
        << ",\"adapter_query_padding_units\":2"
        << ",\"all_source_bounds_covered_by_padding\":"
        << (source.empty() && max_abs_units <= 1 ? "true" : "false") << "}\n";
    return source.empty() && max_abs_units <= 1 ? 0 : 1;
}
