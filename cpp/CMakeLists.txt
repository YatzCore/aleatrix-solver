cmake_minimum_required(VERSION 3.15)
project(yahtzee_core CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Optimize for performance in Release builds
if(MSVC)
    add_compile_options(/O2 /EHsc /W4)
else()
    add_compile_options(-O3 -Wall -Wextra)
endif()

# Find and configure OpenMP for multi-threading
find_package(OpenMP REQUIRED)

include_directories(include)

# 1. Executable target (for benchmarking and validations)
add_executable(yahtzee_core
    src/dice.cpp
    src/scoring.cpp
    src/state.cpp
    src/tablebase.cpp
    src/main.cpp
)
target_link_libraries(yahtzee_core PRIVATE OpenMP::OpenMP_CXX)

# 2. Shared Library target (for Python ctypes integration)
add_library(yahtzee_core_shared SHARED
    src/dice.cpp
    src/scoring.cpp
    src/state.cpp
    src/tablebase.cpp
    src/dll.cpp
)
set_target_properties(yahtzee_core_shared PROPERTIES OUTPUT_NAME "yahtzee_core")
target_link_libraries(yahtzee_core_shared PRIVATE OpenMP::OpenMP_CXX)

# 3. Core regression tests
add_executable(yahtzee_core_tests
    src/dice.cpp
    src/scoring.cpp
    src/state.cpp
    src/tablebase.cpp
    tests/core_tests.cpp
)
target_link_libraries(yahtzee_core_tests PRIVATE OpenMP::OpenMP_CXX)
