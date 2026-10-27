#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// mode: legacy-packed, legacy-sqlite, context-packed, source-sqlite,
// pool-context-packed (repetitions specifies retained independent connections).
// Source mode uses the original host SQLite file for exact SQL result parity.
// It is not necessary to stage that raw baseline on a phone.
char* ysp_storage_benchmark_json(const char* mode,const char* database_path,
    const char* geometry_path,const char* queries_csv,int repetitions,uint64_t rss_gate_bytes);
void ysp_storage_benchmark_free(void* memory);
#ifdef __cplusplus
}
#endif
