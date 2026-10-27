cmake_minimum_required(VERSION 3.16)
project(youspeed_packed_runtime_benchmark LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../..")
find_package(ZLIB REQUIRED)
if(SQLITE_AMALGAMATION_DIR)
  add_library(benchmark_sqlite STATIC "${SQLITE_AMALGAMATION_DIR}/sqlite3.c")
  target_include_directories(benchmark_sqlite PUBLIC "${SQLITE_AMALGAMATION_DIR}")
  target_compile_definitions(benchmark_sqlite PRIVATE SQLITE_ENABLE_RTREE=1 SQLITE_OMIT_LOAD_EXTENSION=1 SQLITE_THREADSAFE=1)
  set(SQLITE_TARGET benchmark_sqlite)
else()
  find_package(SQLite3 REQUIRED)
  set(SQLITE_TARGET SQLite::SQLite3)
endif()
add_executable(packed-runtime-bench main.cpp packed_benchmark.cpp
  "${ROOT}/shared/runtime-storage-prototype/runtime_storage.cpp"
  "${ROOT}/shared/runtime-storage-prototype/packed_runtime.cpp"
  "${ROOT}/shared/runtime-storage-prototype/packed_sqlite_vfs.cpp"
  "${ROOT}/shared/runtime-storage-prototype/zstd_decoder.c")
target_include_directories(packed-runtime-bench PRIVATE "${ROOT}/shared/runtime-storage-prototype")
target_link_libraries(packed-runtime-bench PRIVATE ${SQLITE_TARGET} ZLIB::ZLIB)
