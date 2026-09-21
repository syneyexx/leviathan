#pragma once

#include <functional>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <string>

#include "hades_native/process.hpp"
#include "hades_native/protocol.hpp"
#include "hades_native/resource_governor.hpp"
#include "hades_native/service.hpp"

namespace hades_native {

/// Lightweight stats view so Runtime health can include executor counters.
struct ExecutorStatsView {
    std::size_t worker_count = 0;
    std::size_t queue_capacity = 0;
    std::size_t queued = 0;
    std::size_t active = 0;
    std::uint64_t accepted = 0;
    std::uint64_t rejected_full = 0;
    std::uint64_t completed = 0;
    std::uint64_t cancelled = 0;
    std::uint64_t deadline_exceeded = 0;
};

class Runtime {
public:
    Runtime();
    Json dispatch(const Json& request);
    Json dispatch(const Json& request, const WorkMeta& inbound_meta);
    bool shutdown_requested() const noexcept;
    ResourceGovernor& governor() noexcept { return governor_; }
    const ResourceGovernor& governor() const noexcept { return governor_; }
    void set_executor_stats_provider(std::function<ExecutorStatsView()> provider);

    /// Snapshot health without holding jobs_mutex_ across OS work.
    Json health_snapshot(const ExecutorStatsView& stats = {}) const;

private:
    Json handle(const std::string& method, const Json& params);
    // jobs_mutex_ protects jobs_ map only — never hold across process waits / FS / I/O.
    mutable std::mutex jobs_mutex_;
    std::map<std::string, std::shared_ptr<RunningProcess>> jobs_;
    ServiceManager services_;
    ResourceGovernor governor_;
    std::atomic_bool shutdown_{false};
    std::chrono::steady_clock::time_point started_at_;
    std::function<ExecutorStatsView()> executor_stats_provider_;
};

}  // namespace hades_native
