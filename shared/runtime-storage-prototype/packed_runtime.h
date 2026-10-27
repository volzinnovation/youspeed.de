#ifndef YSP_PACKED_RUNTIME_H
#define YSP_PACKED_RUNTIME_H
#include <stddef.h>
#include <stdint.h>

/* Shared per-connection budgets. Build overrides are intended for measured
 * experiments; production consumers use these defaults via cache_bytes=0 and
 * ysp_sqlite_cache_kib(), so Swift and JNI do not duplicate numeric budgets. */
#ifndef YSP_CONTEXT_CACHE_DEFAULT_BYTES
#define YSP_CONTEXT_CACHE_DEFAULT_BYTES (2 * 1024 * 1024)
#endif
#ifndef YSP_GEOMETRY_CACHE_DEFAULT_BYTES
#define YSP_GEOMETRY_CACHE_DEFAULT_BYTES (512 * 1024)
#endif
#ifndef YSP_SQLITE_CACHE_DEFAULT_KIB
#define YSP_SQLITE_CACHE_DEFAULT_KIB 1536
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Version 1 production storage. Read calls on a handle are serialized safely.
 * Retain handles until all SQLite/proxy-FD/cursor callbacks have stopped.
 * Zero cache_bytes selects 2 MiB for context, 512 KiB for geometry.
 * All file reads use bounded pread, including on 32-bit Android.
 * Errors are copied into caller-owned UTF-8 buffers. */
void* ysp_context_open(const char* path, uint64_t cache_bytes, char* error, size_t error_size);
uint64_t ysp_context_size(void* handle);
int64_t ysp_context_read(void* handle, uint64_t offset, void* output, size_t bytes,
                         char* error, size_t error_size);
void ysp_context_close(void* handle);
void* ysp_geometry_open(const char* path, uint64_t cache_bytes, char* error, size_t error_size);
char* ysp_geometry_json(void* handle, const char* decimal_way_id, char* error, size_t error_size);
void ysp_geometry_close(void* handle);
void ysp_packed_free(void* memory);
int ysp_sqlite_cache_kib(void);
/* Registers read-only SQLite VFS "ysp-packed-v1". Returns SQLITE_OK on success.
 * Link against the same SQLite engine used by the consuming connection. */
int ysp_register_context_vfs(void);
/* VFS module only: diagnostics for a live sqlite3* main connection; NULL when
 * it is not backed by this VFS. Android proxy handles use context_stats below. */
char* ysp_context_vfs_stats_json(void* sqlite_database);

/* Optional diagnostics; malloc-owned JSON, release with ysp_packed_free.
 * These report actual cache resident/peak bytes, read counts and mapped_bytes=0.
 * They do not claim to cap the caller's strings, SQLite cache, or process RSS. */
char* ysp_context_stats_json(void* handle);
char* ysp_geometry_stats_json(void* handle);

#ifdef __cplusplus
}
#endif
#endif
