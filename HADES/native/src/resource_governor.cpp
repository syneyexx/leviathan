#include "hades_native/resource_governor.hpp"

#include <algorithm>
#include <cstdlib>
#include <thread>

namespace hades_native {
namespace {
std::size_t env_size(const char* name, std::size_t fallback, std::size_t lo, std::size_t hi) {
    const char* raw = std::getenv(name);
    if (!raw || !*raw) return fallback;
    char* end = nullptr;
    const auto value = std::strtoull(raw, &end, 10);
    if (end == raw || value == 0) return fallback;
    return std::clamp<std::size_t>(static_cast<std::size_t>(value), lo, hi);
}
}  // namespace

ResourceGovernor::ResourceGovernor(std::size_t max_concurrent_processes)
    : max_concurrent_(max_concurrent_processes ? max_concurrent_processes
                                               : env_size("HADES_NATIVE_MAX_PROCESSES", 32, 1, 256)) {}

bool ResourceGovernor::try_acquire_process_slot() {
    std::size_t current = active_processes_.load(std::memory_order_relaxed);
    while (current < max_concurrent_) {
        if (active_processes_.compare_exchange_weak(current, current + 1, std::memory_order_acq_rel)) {
            return true;
        }
    }
    return false;
}

void ResourceGovernor::release_process_slot() noexcept {
    active_processes_.fetch_sub(1, std::memory_order_acq_rel);
}

Json ResourceGovernor::capabilities() const {
    return {
        {"process_tree_kill", true},
#ifdef _WIN32
        {"job_objects", true},
        {"memory_limit", false},  // not implemented; do not claim support
#else
        {"job_objects", false},
        {"memory_limit", false},
#endif
        {"wall_clock_timeout", true},
        {"max_output_capture", true},
        {"max_concurrent_processes", true},
        {"cpu_accounting", false},
    };
}

Json ResourceGovernor::snapshot() const {
    return {
        {"active_processes", active_processes_.load()},
        {"max_concurrent_processes", max_concurrent_},
        {"hardware_concurrency", std::thread::hardware_concurrency()},
    };
}

}  // namespace hades_native
