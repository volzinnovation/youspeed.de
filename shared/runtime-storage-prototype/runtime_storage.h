#ifndef YSP_RUNTIME_STORAGE_H
#define YSP_RUNTIME_STORAGE_H
#ifdef __cplusplus
extern "C" {
#endif
/* Returned UTF-8 JSON is malloc-owned and must be released with storage_free.
 * kind: packed|sqlite|geodesk. GeoDesk path is GOL_PATH|SQLITE_PATH.
 * CSV CONTENTS: lat,lon,radius_m, one numeric query per line, optional header.
 * Experimental isolated lookup kernel; does not modify installed app behavior. */
char* storage_benchmark_json(const char* kind, const char* path, const char* queries_csv, int repetitions);
char* storage_query_json(const char* kind, const char* path, double lat, double lon, double radius_m);
char* storage_query_batch_json(const char* kind, const char* path, const char* queries_csv);
char* storage_way_json(const char* kind, const char* path, long long way_id);
void storage_free(void* value);
#ifdef __cplusplus
}
#endif
#endif
