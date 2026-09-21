#pragma once

#include <atomic>
#include <cstddef>
#include <mutex>

#include "hades_native/protocol.hpp"

namespace hades_native {

/// Tracks concurrent native child processes and truthful capability flags.
/// Does not pretend unsupported OS controls exist.
class ResourceGovernor {
public:
    explicit ResourceGovernor(std::size_t max_concurrent_processes = 32);

    /// Try to acquire a process slot. Returns false when saturated.
    bool try_acquire_process_slot();
    void release_process_slot() noexcept;

    std::size_t active_processes() const noexcept { return active_processes_.load(); }
    std::size_t max_concurrent_processes() const noexcept { return max_concurrent_; }

    Json capabilities() const;
    Json snapshot() const;

private:
    const std::size_t max_concurrent_;
    std::atomic<std::size_t> active_processes_{0};
};

/// RAII process-slot guard.
class ProcessSlotGuard {
public:
    explicit ProcessSlotGuard(ResourceGovernor& governor) : governor_(&governor), held_(governor.try_acquire_process_slot()) {}
    ~ProcessSlotGuard() {
        if (held_ && governor_) governor_->release_process_slot();
    }
    ProcessSlotGuard(const ProcessSlotGuard&) = delete;
    ProcessSlotGuard& operator=(const ProcessSlotGuard&) = delete;
    ProcessSlotGuard(ProcessSlotGuard&& other) noexcept : governor_(other.governor_), held_(other.held_) {
        other.held_ = false;
        other.governor_ = nullptr;
    }
    bool acquired() const noexcept { return held_; }

private:
    ResourceGovernor* governor_;
    bool held_;
};

}  // namespace hades_native
