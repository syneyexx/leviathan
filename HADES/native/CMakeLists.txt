cmake_minimum_required(VERSION 3.20)

project(hades_native_runtime VERSION 0.2.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(HADES_NATIVE_SANITIZE_ADDRESS "Build with AddressSanitizer" OFF)
option(HADES_NATIVE_SANITIZE_UNDEFINED "Build with UndefinedBehaviorSanitizer" OFF)
option(HADES_NATIVE_SANITIZE_THREAD "Build with ThreadSanitizer" OFF)

if(MSVC)
    # /MP: parallel translation units (avoids one giant cl.exe batch that sits on "Generating Code...").
    # /cgthreads8: parallelize MSVC backend codegen within each cl.exe process.
    # Must be set before targets are created so directory-level flags apply.
    add_compile_options(/W4 /permissive- /MP /cgthreads8)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

add_library(hades_native_core
    src/protocol.cpp
    src/runtime.cpp
    src/filesystem.cpp
    src/process_win32.cpp
    src/service_win32.cpp
    src/metrics_win32.cpp
    src/executor.cpp
    src/resource_governor.cpp
)
target_include_directories(hades_native_core
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/third_party
)
target_compile_definitions(hades_native_core PRIVATE
    $<$<BOOL:${WIN32}>:NOMINMAX;WIN32_LEAN_AND_MEAN>
)

function(hades_apply_sanitizers target)
    if(MSVC)
        return()
    endif()
    if(HADES_NATIVE_SANITIZE_THREAD AND (HADES_NATIVE_SANITIZE_ADDRESS OR HADES_NATIVE_SANITIZE_UNDEFINED))
        message(FATAL_ERROR "ThreadSanitizer cannot be combined with ASan/UBSan")
    endif()
    if(HADES_NATIVE_SANITIZE_ADDRESS)
        target_compile_options(${target} PRIVATE -fsanitize=address -fno-omit-frame-pointer)
        target_link_options(${target} PRIVATE -fsanitize=address)
    endif()
    if(HADES_NATIVE_SANITIZE_UNDEFINED)
        target_compile_options(${target} PRIVATE -fsanitize=undefined -fno-omit-frame-pointer)
        target_link_options(${target} PRIVATE -fsanitize=undefined)
    endif()
    if(HADES_NATIVE_SANITIZE_THREAD)
        target_compile_options(${target} PRIVATE -fsanitize=thread -fno-omit-frame-pointer)
        target_link_options(${target} PRIVATE -fsanitize=thread)
    endif()
endfunction()

function(hades_enable_test_assertions target)
    # CMake's Release configuration defines NDEBUG. These executables are the
    # release gate itself, so compiling out assert(...) turns behavioral checks
    # into no-ops and even creates misleading "unused variable" warnings.
    if(MSVC)
        target_compile_options(${target} PRIVATE /UNDEBUG)
    else()
        target_compile_options(${target} PRIVATE -UNDEBUG)
    endif()
endfunction()

hades_apply_sanitizers(hades_native_core)
if(MSVC)
    set_property(TARGET hades_native_core PROPERTY VS_GLOBAL_UseMultiToolTask true)
    set_property(TARGET hades_native_core PROPERTY VS_GLOBAL_EnforceProcessCountAcrossBuilds true)
endif()

add_executable(hades_native_runtime src/main.cpp)
target_link_libraries(hades_native_runtime PRIVATE hades_native_core)
hades_apply_sanitizers(hades_native_runtime)

if(WIN32)
    target_link_libraries(hades_native_core PRIVATE bcrypt)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(runtime_tests tests/runtime_tests.cpp)
    target_link_libraries(runtime_tests PRIVATE hades_native_core)
    target_include_directories(runtime_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
    hades_apply_sanitizers(runtime_tests)
    hades_enable_test_assertions(runtime_tests)
    add_test(NAME runtime_tests COMMAND runtime_tests)

    add_executable(executor_tests tests/executor_tests.cpp)
    target_link_libraries(executor_tests PRIVATE hades_native_core)
    hades_apply_sanitizers(executor_tests)
    hades_enable_test_assertions(executor_tests)
    add_test(NAME executor_tests COMMAND executor_tests)

    add_executable(native_bench tests/native_bench.cpp)
    target_link_libraries(native_bench PRIVATE hades_native_core)
    hades_apply_sanitizers(native_bench)
endif()

install(TARGETS hades_native_runtime RUNTIME DESTINATION runtime/native)
