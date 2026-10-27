cmake_minimum_required(VERSION 3.22)
project(youspeed_packed_runtime LANGUAGES C CXX)
get_filename_component(REPO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../.." ABSOLUTE)
add_library(youspeed_packed_runtime SHARED
    packed_runtime_jni.cpp
    packed_sqlite_jni.cpp
    vendor/sqlite/sqlite3.c
    "${REPO_ROOT}/shared/runtime-storage-prototype/zstd_decoder.c"
    "${REPO_ROOT}/shared/runtime-storage-prototype/packed_runtime.cpp"
    "${REPO_ROOT}/shared/runtime-storage-prototype/packed_sqlite_vfs.cpp"
    "${REPO_ROOT}/shared/runtime-sign-nodes-prototype/runtime_sign_nodes.cpp")
target_compile_features(youspeed_packed_runtime PRIVATE cxx_std_17)
target_compile_definitions(youspeed_packed_runtime PRIVATE _FILE_OFFSET_BITS=64 YSP_NODES_PACKED_ONLY=1
    SQLITE_ENABLE_RTREE=1 SQLITE_OMIT_LOAD_EXTENSION=1 SQLITE_THREADSAFE=1)
set_target_properties(youspeed_packed_runtime PROPERTIES C_VISIBILITY_PRESET hidden CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
target_include_directories(youspeed_packed_runtime PRIVATE
    "${REPO_ROOT}/shared/runtime-storage-prototype"
    "${REPO_ROOT}/shared/runtime-sign-nodes-prototype"
    "${CMAKE_CURRENT_LIST_DIR}/vendor/sqlite")
target_link_libraries(youspeed_packed_runtime PRIVATE z)
target_link_options(youspeed_packed_runtime PRIVATE "-Wl,-z,max-page-size=16384")
