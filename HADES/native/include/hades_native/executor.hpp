#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "hades_native/protocol.hpp"

namespace hades_native {

/// Bounded work item for the RPC executor.
struct WorkItem {
    Json request;
    Json id;
    std::string method;
    std::chrono::steady_clock::time_point enqueued_at{};
    std::optional<std::chrono::steady_clock::time_point> deadline{};
    std::atomic_bool* cancel_flag = nullptr;  // optional external cancel
};

struct ExecutorStats {
    std::size_t worker_count = 0;
    std::size_t queue_capacity = 0;
    std::size_t queued = 0;
    std::size_t active = 0;
    std::uint64_t accepted = 0;
    std::uint64_t rejected_full = 0;
    std::uint64_t rejected_shutdown = 0;
    std::uint64_t completed = 0;
    std::uint64_t cancelled = 0;
    std::uint64_t deadline_exceeded = 0;
};

enum class SubmitResult {
    Accepted,
    QueueFull,
    ShuttingDown,
};

/// Production-quality bounded worker pool (no request-per-thread).
/// stdin reader submits; workers execute; responses written via callback.
class BoundedExecutor {
public:
    using Handler = std::function<Json(const Json& request, const WorkMeta& meta)>;
    using Writer = std::function<void(const Json& response)>;

    BoundedExecutor(std::size_t workers, std::size_t queue_capacity, Handler handler, Writer writer);
    ~BoundedExecutor();

    BoundedExecutor(const BoundedExecutor&) = delete;
    BoundedExecutor& operator=(const BoundedExecutor&) = delete;

    SubmitResult try_submit(WorkItem item);
    void request_shutdown();
    void join();
    bool shutting_down() const noexcept { return shutting_down_.load(); }
    ExecutorStats stats() const;

    static std::size_t default_worker_count() noexcept;
    static std::size_t default_queue_capacity() noexcept;

private:
    void worker_main(std::stop_token stop, unsigned worker_id);
    bool pop_work(std::stop_token stop, WorkItem& out);
    void complete_with_error(WorkItem& item, const char* code, const char* message, Json details = Json::object());

    Handler handler_;
    Writer writer_;
    const std::size_t queue_capacity_;
    mutable std::mutex mutex_;
    std::condition_variable_any cv_nonempty_;
    std::condition_variable cv_nonsfull_;
    std::deque<WorkItem> queue_;
    std::vector<std::jthread> workers_;
    std::atomic_bool shutting_down_{false};
    std::atomic<std::size_t> active_{0};
    std::atomic<std::uint64_t> accepted_{0};
    std::atomic<std::uint64_t> rejected_full_{0};
    std::atomic<std::uint64_t> rejected_shutdown_{0};
    std::atomic<std::uint64_t> completed_{0};
    std::atomic<std::uint64_t> cancelled_{0};
    std::atomic<std::uint64_t> deadline_exceeded_{0};
};

std::size_t resolve_worker_count_from_env() noexcept;
std::size_t resolve_queue_capacity_from_env() noexcept;

}  // namespace hades_native
