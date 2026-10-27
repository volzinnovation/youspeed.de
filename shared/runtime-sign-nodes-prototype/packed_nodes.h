#ifndef YSP_PACKED_NODES_H
#define YSP_PACKED_NODES_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Persistent, thread-safe, read-only generic source nodes. Empty packs are
 * valid. A zero cache selects 512 KiB of pread pages; no file is mapped.
 * JSON contains complete canonical source records and unchanged restrictions,
 * tags, provenance and memberships. Membership never implies applicability.
 * Stop all callbacks before closing a handle. Errors use caller-owned buffers.
 * Returned strings are malloc-owned; release with ysp_nodes_free. */
void* ysp_nodes_open(const char* path,uint64_t cache_bytes,char* error,size_t error_size);
char* ysp_nodes_json(void* handle,const char* decimal_node_id,char* error,size_t error_size);
char* ysp_nodes_query_json(void* handle,double lat,double lon,double radius_m,char* error,size_t error_size);
char* ysp_nodes_stats_json(void* handle);
void ysp_nodes_close(void* handle);
void ysp_nodes_free(void* memory);
#ifdef __cplusplus
}
#endif
#endif
