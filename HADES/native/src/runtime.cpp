#include "hades_native/runtime.hpp"

#include <stdexcept>

#include "hades_native/filesystem.hpp"
#include "hades_native/metrics.hpp"
#include "hades_native/version.hpp"

namespace hades_native {
Runtime::Runtime() : started_at_(std::chrono::steady_clock::now()) {}

void Runtime::set_executor_stats_provider(std::function<ExecutorStatsView()> provider) {
    executor_stats_provider_ = std::move(provider);
}

Json Runtime::dispatch(const Json& request) {
    return dispatch(request, WorkMeta{});
}

Json Runtime::dispatch(const Json& request, const WorkMeta& inbound_meta) {
    RpcError validation;
    const Json id = request.contains("id") ? request["id"] : Json(nullptr);
    if (!validate_request(request, validation)) return error_response(id, validation, inbound_meta);
    const auto started = std::chrono::steady_clock::now();
    WorkMeta meta = inbound_meta;
    try {
        auto result = handle(request["method"].get<std::string>(), request.value("params", Json::object()));
        meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
        return success_response(id, std::move(result), meta);
    } catch (const std::invalid_argument& error) {
        meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
        return error_response(id, {"INVALID_PARAMS", error.what(), Json::object()}, meta);
    } catch (const std::runtime_error& error) {
        meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
        const std::string message = error.what();
        if (message.rfind("UNSUPPORTED:", 0) == 0)
            return error_response(id, {"UNKNOWN_METHOD", message.substr(12), Json::object()}, meta);
        if (message.rfind("OVERLOADED:", 0) == 0)
            return error_response(id, {"OVERLOADED", message.substr(11), Json::object()}, meta);
        if (message.rfind("CANCELLED:", 0) == 0)
            return error_response(id, {"CANCELLED", message.substr(10), Json::object()}, meta);
        if (message.rfind("SHUTTING_DOWN:", 0) == 0)
            return error_response(id, {"SHUTTING_DOWN", message.substr(14), Json::object()}, meta);
        return error_response(id, {"RUNTIME_ERROR", message, Json::object()}, meta);
    } catch (const std::exception& error) {
        meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
        // Stable API code — do not leak unstable exception type names as protocol semantics.
        return error_response(id, {"INTERNAL_ERROR", "native handler failed", {{"detail", error.what()}}}, meta);
    }
}

Json Runtime::health_snapshot(const ExecutorStatsView& stats) const {
    std::size_t job_count = 0;
    {
        std::lock_guard lock(jobs_mutex_);
        job_count = jobs_.size();
    }
    const auto uptime = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started_at_).count();
    return {
        {"healthy", !shutdown_},
        {"shutdown_requested", shutdown_requested()},
        {"uptime_ms", uptime},
        {"active_jobs", job_count},
        {"active_services", services_.active_count()},
        {"active_processes", governor_.active_processes()},
        {"workers", stats.worker_count},
        {"queued", stats.queued},
        {"active_workers", stats.active},
        {"queue_capacity", stats.queue_capacity},
        {"accepted", stats.accepted},
        {"rejected_full", stats.rejected_full},
        {"completed", stats.completed},
        {"cancelled", stats.cancelled},
        {"deadline_exceeded", stats.deadline_exceeded},
        {"version", kVersion},
        {"protocol_version", kProtocolVersion},
    };
}

Json Runtime::handle(const std::string& method, const Json& params) {
    if (shutdown_ && method != "runtime.shutdown") throw std::runtime_error("SHUTTING_DOWN: runtime is shutting down");
    if (method == "runtime.hello")
        return {{"runtime", "hades_native_runtime"},
                {"version", kVersion},
                {"protocol_version", kProtocolVersion},
                {"platform",
#ifdef _WIN32
                 "windows"
#else
                 "linux"
#endif
                }};
    if (method == "runtime.health") {
        ExecutorStatsView stats;
        if (executor_stats_provider_) stats = executor_stats_provider_();
        return health_snapshot(stats);
    }
    if (method == "runtime.capabilities") {
        auto caps = governor_.capabilities();
        caps["process"] = true;
        caps["services"] = true;
        caps["filesystem"] = true;
        caps["sha256"] = true;
        caps["fs_hash_many"] = true;
        caps["fs_snapshot"] = true;
        caps["repo_search"] = true;
        caps["bounded_executor"] = true;
        caps["cancellation"] = true;
        caps["deadlines"] = true;
        return caps;
    }
    if (method == "runtime.shutdown") {
        shutdown_ = true;
        // Snapshot job pointers under lock, then cancel without holding the mutex across OS kill.
        std::vector<std::shared_ptr<RunningProcess>> to_cancel;
        {
            std::lock_guard lock(jobs_mutex_);
            to_cancel.reserve(jobs_.size());
            for (auto& [_, job] : jobs_) to_cancel.push_back(job);
        }
        for (auto& job : to_cancel) {
            std::string ignored;
            cancel_process(*job, ignored);
        }
        return {{"shutdown", true}};
    }
    if (method == "process.run") {
        static std::atomic<unsigned long long> sequence{0};
        const auto job_id = params.value("job_id", "job-" + std::to_string(++sequence));
        if (job_id.empty()) throw std::invalid_argument("job_id must not be empty");
        ProcessSlotGuard slot(governor_);
        if (!slot.acquired()) throw std::runtime_error("OVERLOADED: maximum concurrent processes reached");
        auto job = std::make_shared<RunningProcess>();
        {
            std::lock_guard lock(jobs_mutex_);
            if (shutdown_) throw std::runtime_error("SHUTTING_DOWN: runtime is shutting down");
            if (!jobs_.emplace(job_id, job).second) throw std::runtime_error("job_id is already running");
        }
        // Cancel-before-start race: if cancel already flipped the flag, abort early.
        if (job->cancel_requested.load()) {
            std::lock_guard lock(jobs_mutex_);
            jobs_.erase(job_id);
            throw std::runtime_error("CANCELLED: cancelled before process start");
        }
        try {
            // Blocking process wait happens WITHOUT jobs_mutex_.
            const auto outcome = run_process(parse_process_request(params), *job);
            {
                std::lock_guard lock(jobs_mutex_);
                jobs_.erase(job_id);
            }
            return {{"job_id", job_id},
                    {"pid", outcome.pid},
                    {"exit_code", outcome.exit_code},
                    {"timed_out", outcome.timed_out},
                    {"cancelled", outcome.cancelled},
                    {"stdout", outcome.stdout_data},
                    {"stderr", outcome.stderr_data},
                    {"stdout_truncated", outcome.stdout_truncated},
                    {"stderr_truncated", outcome.stderr_truncated}};
        } catch (...) {
            std::lock_guard lock(jobs_mutex_);
            jobs_.erase(job_id);
            throw;
        }
    }
    if (method == "process.cancel") {
        const auto job_id = params.value("job_id", "");
        if (job_id.empty()) throw std::invalid_argument("job_id is required");
        std::shared_ptr<RunningProcess> job;
        {
            std::lock_guard lock(jobs_mutex_);
            const auto it = jobs_.find(job_id);
            if (it == jobs_.end()) {
                // Idempotent: unknown/completed job is a soft success for duplicate cancel.
                return {{"job_id", job_id}, {"cancel_requested", true}, {"message", "unknown or completed job"}, {"idempotent", true}};
            }
            job = it->second;
        }
        // Cancel OS resources outside the map lock.
        std::string error;
        const bool cancelled = cancel_process(*job, error);
        return {{"job_id", job_id}, {"cancel_requested", cancelled || job->cancel_requested.load()}, {"message", error}, {"idempotent", false}};
    }
    if (method == "service.start") return services_.start(params);
    if (method == "service.status") return services_.status(params);
    if (method == "service.stop") return services_.stop(params);
    if (method == "service.logs") return services_.logs(params);
    if (method == "service.probe") return services_.probe(params);
    if (method == "fs.scan") return scan_filesystem(params);
    if (method == "fs.hash") return hash_file(params);
    if (method == "fs.hash_many") return hash_many(params);
    if (method == "fs.snapshot") return snapshot_filesystem(params);
    if (method == "repo.scan") return snapshot_filesystem(params);
    if (method == "repo.search") return search_repository(params);
    if (method == "system.metrics") {
        std::size_t job_count = 0;
        {
            std::lock_guard lock(jobs_mutex_);
            job_count = jobs_.size();
        }
        auto metrics = system_metrics(job_count);
        metrics["resource_governor"] = governor_.snapshot();
        return metrics;
    }
    throw std::runtime_error("UNSUPPORTED: unknown method " + method);
}

bool Runtime::shutdown_requested() const noexcept { return shutdown_; }
}  // namespace hades_native
