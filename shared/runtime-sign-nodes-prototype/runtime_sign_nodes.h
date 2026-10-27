#pragma once
#ifdef __cplusplus
extern "C" {
#endif
// All returned strings are malloc-owned; release with storage_nodes_free.
// CSV contents are lat,lon,radius_m. GeoDesk path is GOL_PATH|NODES_SQLITE_PATH.
char* storage_nodes_benchmark_json(const char* kind,const char* path,const char* csv,int repetitions);
char* storage_nodes_query_json(const char* kind,const char* path,double lat,double lon,double radius_m);
char* storage_node_json(const char* kind,const char* path,long long node_id);
// Validates all directory entries and full canonical metadata, returns corpus digest.
char* storage_nodes_roundtrip_json(const char* kind,const char* path);
char* storage_nodes_compare_json(const char* firstKind,const char* firstPath,
    const char* secondKind,const char* secondPath,const char* csv);
void storage_nodes_free(void* value);
#ifdef __cplusplus
}
#endif
