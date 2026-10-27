#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="${1:?output directory required}"
mkdir -p "$out"
cc -O2 -fPIC -fvisibility=hidden -c "$root/shared/packed-runtime/vendor/zstd/zstddeclib.c" -o "$out/zstddeclib.o"
c++ -std=c++17 -O2 -fPIC -shared -pthread \
  "$root/inspector/native_bundle.cpp" \
  "$root/shared/runtime-storage-prototype/packed_runtime.cpp" \
  "$root/shared/runtime-storage-prototype/packed_sqlite_vfs.cpp" \
  "$root/shared/runtime-sign-nodes-prototype/runtime_sign_nodes.cpp" \
  "$out/zstddeclib.o" -lsqlite3 -lz -o "$out/libinspector_bundle.so"
