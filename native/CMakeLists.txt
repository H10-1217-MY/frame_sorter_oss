cmake_minimum_required(VERSION 3.18)
project(frame_sorter_fast_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(fast_core src/bindings.cpp)

set(OUTPUT_DIR "${CMAKE_SOURCE_DIR}/../frame_sorter/native_ext")

set_target_properties(
    fast_core
    PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${OUTPUT_DIR}"
    RUNTIME_OUTPUT_DIRECTORY "${OUTPUT_DIR}"
)

foreach(CONFIG Debug Release RelWithDebInfo MinSizeRel)
    string(TOUPPER "${CONFIG}" CONFIG_UPPER)
    set_target_properties(
        fast_core
        PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY_${CONFIG_UPPER} "${OUTPUT_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_${CONFIG_UPPER} "${OUTPUT_DIR}"
    )
endforeach()
