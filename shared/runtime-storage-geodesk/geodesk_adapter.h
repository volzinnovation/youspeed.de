#ifndef YOUSPEED_RUNTIME_STORAGE_GEODESK_H
#define YOUSPEED_RUNTIME_STORAGE_GEODESK_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Each handle must be confined to a single thread. The library remains mapped
 * until close. All results are OSM way IDs, with no semantic policy applied. */
void* storage_geodesk_open(const char* gol_path, char* err, size_t err_len);
int storage_geodesk_candidates(void* handle, double min_lon, double min_lat,
    double max_lon, double max_lat, int64_t** ids, size_t* count);
int storage_geodesk_node_candidates(void* handle, double min_lon, double min_lat,
    double max_lon, double max_lat, int64_t** ids, size_t* count);
void storage_geodesk_free_ids(int64_t* ids);
void storage_geodesk_close(void* handle);

#ifdef __cplusplus
}
#endif
#endif
