cmake_minimum_required(VERSION 3.20)
project(youspeed_runtime_storage_geodesk LANGUAGES CXX)

# Prototype only. Sources are pinned and fetched by the companion script, never
# fetched during a native/mobile build. No GEOS, Python, HTTP or tests are linked
# into this read-only adapter.
set(GEODESK_SOURCE_DIR "" CACHE PATH "Pinned libgeodesk source directory")
set(GTL_SOURCE_DIR "" CACHE PATH "Pinned gtl source directory")
if(NOT EXISTS "${GEODESK_SOURCE_DIR}/include/geodesk/geodesk.h")
  message(FATAL_ERROR "Set GEODESK_SOURCE_DIR to the pinned source checkout")
endif()
if(NOT EXISTS "${GTL_SOURCE_DIR}/include/gtl/phmap.hpp")
  message(FATAL_ERROR "Set GTL_SOURCE_DIR to gtl v1.2.0")
endif()
file(GLOB_RECURSE GEODESK_SOURCES CONFIGURE_DEPENDS "${GEODESK_SOURCE_DIR}/src/*.cpp")
add_library(storage_geodesk STATIC ${GEODESK_SOURCES} geodesk_adapter.cpp)
target_compile_features(storage_geodesk PRIVATE cxx_std_20)
target_include_directories(storage_geodesk PRIVATE
  "${GEODESK_SOURCE_DIR}/include" "${GEODESK_SOURCE_DIR}/src"
  "${GTL_SOURCE_DIR}/include")
target_include_directories(storage_geodesk PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
set_target_properties(storage_geodesk PROPERTIES POSITION_INDEPENDENT_CODE ON)

option(STORAGE_GEODESK_BUILD_TOOL "Build the pinned host GOL builder" OFF)
if(STORAGE_GEODESK_BUILD_TOOL)
  set(GOL_SOURCE_DIR "" CACHE PATH "Pinned geodesk-gol source directory")
  set(HTTPLIB_INCLUDE_DIR "" CACHE PATH "Directory with pinned httplib.h")
  find_package(ZLIB REQUIRED)
  find_package(OpenSSL REQUIRED)
  find_package(SQLite3 REQUIRED)
  file(GLOB_RECURSE GOL_SOURCES CONFIGURE_DEPENDS "${GOL_SOURCE_DIR}/src/*.cpp")
  add_executable(storage_gol ${GOL_SOURCES})
  target_compile_features(storage_gol PRIVATE cxx_std_20)
  target_compile_definitions(storage_gol PRIVATE
    GOL_BUILD_STATS CLARISMA_WITH_ZLIB CPPHTTPLIB_OPENSSL_SUPPORT
    GEODESK_GOL_VERSION="0.0.0-pinned-258dde3")
  target_include_directories(storage_gol PRIVATE
    "${GOL_SOURCE_DIR}/include" "${GOL_SOURCE_DIR}/src"
    "${GEODESK_SOURCE_DIR}/include" "${GTL_SOURCE_DIR}/include"
    "${HTTPLIB_INCLUDE_DIR}")
  target_link_libraries(storage_gol PRIVATE storage_geodesk
    ZLIB::ZLIB OpenSSL::SSL OpenSSL::Crypto)
  if(APPLE)
    target_link_libraries(storage_gol PRIVATE "-framework CoreFoundation" "-framework Security")
  endif()
  add_executable(storage_geodesk_verify_bounds verify_native_bounds.cpp)
  target_compile_features(storage_geodesk_verify_bounds PRIVATE cxx_std_20)
  target_include_directories(storage_geodesk_verify_bounds PRIVATE
    "${GEODESK_SOURCE_DIR}/include" "${GTL_SOURCE_DIR}/include")
  target_link_libraries(storage_geodesk_verify_bounds PRIVATE storage_geodesk SQLite::SQLite3)
endif()
