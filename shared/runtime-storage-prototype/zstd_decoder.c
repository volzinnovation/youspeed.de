/* Keep the pinned decoder private to this runtime. In particular, its
 * advanced frame-header API must not interpose with a different SDK's zstd.
 * Upstream source and its BSD notice remain unmodified in vendor/zstd. */
#include <assert.h>
#include <inttypes.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* System declarations must retain their platform visibility. Their include
 * guards keep the upstream amalgamation from redeclaring libc as hidden. */
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC visibility push(hidden)
#define ZSTDLIB_VISIBLE __attribute__((visibility("hidden")))
#endif
#include "../packed-runtime/vendor/zstd/zstddeclib.c"
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC visibility pop
#endif
