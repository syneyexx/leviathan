#include "hades_native/executor.hpp"

#include <algorithm>
#include <cstdlib>

namespace hades_native {
namespace {
std::size_t env_size(const char* name, std::size_t fallback, std::size_t lo, std::size_t hi) noexcept {
    const char* raw = std::getenv(name);
    if (!raw || !*raw) return fallback;
    char* end = nullptr;
    const unsigned long long value = std::strtoull(raw, &end, 10);
    if (end == raw || value == 0) return fallback;
    return std::clamp(static_cast<std::size_t>(value), lo, hi);
}
}  // namespace

std::size_t BoundedExecutor::default_worker_count() noexcept {
    const unsigned hc = std::thread::hardware_concurrency();
    const std::size_t fallback = hc == 0 ? 4 : std::clamp<std::size_t>(hc, 2, 16);
    return env_size("HADES_NATIVE_WORKERS", fallback, 1, 64);
}

std::size_t BoundedExecutor::default_queue_capacity() noexcept {
    return env_size("HADES_NATIVE_QUEUE", 256, 8, 8192);
}

std::size_t resolve_worker_count_from_env() noexcept { return BoundedExecutor::default_worker_count(); }
std::size_t resolve_queue_capacity_from_env() noexcept { return BoundedExecutor::default_queue_capacity(); }

BoundedExecutor::BoundedExecutor(std::size_t workers, std::size_t queue_capacity, Handler handler, Writer writer)
    : handler_(std::move(handler)),
      writer_(std::move(writer)),
      queue_capacity_(queue_capacity == 0 ? default_queue_capacity() : queue_capacity) {
    const std::size_t count = workers == 0 ? default_worker_count() : workers;
    workers_.reserve(count);
    for (unsigned i = 0; i < count; ++i) {
        workers_.emplace_back([this, i](std::stop_token stop) { worker_main(stop, i + 1); });
    }
}

BoundedExecutor::~BoundedExecutor() {
    request_shutdown();
    join();
}

SubmitResult BoundedExecutor::try_submit(WorkItem item) {
    if (shutting_down_.load(std::memory_order_acquire)) {
        rejected_shutdown_.fetch_add(1, std::memory_order_relaxed);
        return SubmitResult::ShuttingDown;
    }
    {
        std::lock_guard lock(mutex_);
        if (shutting_down_.load(std::memory_order_relaxed)) {
            rejected_shutdown_.fetch_add(1, std::memory_order_relaxed);
            return SubmitResult::ShuttingDown;
        }
        if (queue_.size() >= queue_capacity_) {
            rejected_full_.fetch_add(1, std::memory_order_relaxed);
            return SubmitResult::QueueFull;
        }
        item.enqueued_at = std::chrono::steady_clock::now();
        queue_.push_back(std::move(item));
        accepted_.fetch_add(1, std::memory_order_relaxed);
    }
    cv_nonempty_.notify_one();
    return SubmitResult::Accepted;
}

void BoundedExecutor::request_shutdown() {
    shutting_down_.store(true, std::memory_order_release);
    for (auto& worker : workers_) {
        worker.request_stop();
    }
    cv_nonempty_.notify_all();
    cv_nonsfull_.notify_all();
}

void BoundedExecutor::join() {
    for (auto& worker : workers_) {
        if (worker.joinable()) worker.join();
    }
    workers_.clear();
}

ExecutorStats BoundedExecutor::stats() const {
    ExecutorStats out;
    out.worker_count = workers_.size();
    out.queue_capacity = queue_capacity_;
    {
        std::lock_guard lock(mutex_);
        out.queued = queue_.size();
    }
    out.active = active_.load();
    out.accepted = accepted_.load();
    out.rejected_full = rejected_full_.load();
    out.rejected_shutdown = rejected_shutdown_.load();
    out.completed = completed_.load();
    out.cancelled = cancelled_.load();
    out.deadline_exceeded = deadline_exceeded_.load();
    return out;
}

bool BoundedExecutor::pop_work(std::stop_token stop, WorkItem& out) {
    std::unique_lock lock(mutex_);
    cv_nonempty_.wait(lock, stop, [this] { return !queue_.empty() || shutting_down_.load(std::memory_order_relaxed); });
    if (queue_.empty()) return false;
    out = std::move(queue_.front());
    queue_.pop_front();
    cv_nonsfull_.notify_one();
    return true;
}

void BoundedExecutor::complete_with_error(WorkItem& item, const char* code, const char* message, Json details) {
    WorkMeta meta;
    meta.queue_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - item.enqueued_at).count();
    writer_(error_response(item.id, {code, message, std::move(details)}, meta));
}

void BoundedExecutor::worker_main(std::stop_token stop, unsigned worker_id) {
    while (!stop.stop_requested()) {
        WorkItem item;
        if (!pop_work(stop, item)) {
            if (shutting_down_.load(std::memory_order_acquire)) break;
            continue;
        }

        WorkMeta meta;
        meta.worker_id = worker_id;
        meta.queue_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - item.enqueued_at).count();

        // Cancelled while queued
        if (item.cancel_flag && item.cancel_flag->load(std::memory_order_acquire)) {
            cancelled_.fetch_add(1, std::memory_order_relaxed);
            complete_with_error(item, "CANCELLED", "Request cancelled before execution");
            continue;
        }

        // Deadline exceeded while queued
        if (item.deadline && std::chrono::steady_clock::now() >= *item.deadline) {
            deadline_exceeded_.fetch_add(1, std::memory_order_relaxed);
            complete_with_error(item, "DEADLINE_EXCEEDED", "Request deadline exceeded while queued");
            continue;
        }

        if (shutting_down_.load(std::memory_order_acquire) && item.method != "runtime.shutdown") {
            complete_with_error(item, "SHUTTING_DOWN", "Native runtime is shutting down");
            continue;
        }

        active_.fetch_add(1, std::memory_order_relaxed);
        const auto started = std::chrono::steady_clock::now();
        try {
            Json response = handler_(item.request, meta);
            meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
            // Attach timing if handler returned a bare success without meta merge — handler uses Runtime::dispatch
            // which already embeds meta; ensure queue_ms/worker_id are present.
            if (response.is_object()) {
                if (!response.contains("meta") || !response["meta"].is_object()) response["meta"] = Json::object();
                response["meta"]["queue_ms"] = meta.queue_ms;
                response["meta"]["worker_id"] = meta.worker_id;
                if (!response["meta"].contains("duration_ms")) response["meta"]["duration_ms"] = meta.duration_ms;
            }
            writer_(response);
            completed_.fetch_add(1, std::memory_order_relaxed);
        } catch (const std::exception& ex) {
            meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
            writer_(error_response(item.id, {"INTERNAL_ERROR", ex.what(), Json::object()}, meta));
            completed_.fetch_add(1, std::memory_order_relaxed);
        } catch (...) {
            meta.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started).count();
            writer_(error_response(item.id, {"INTERNAL_ERROR", "unknown native exception", Json::object()}, meta));
            completed_.fetch_add(1, std::memory_order_relaxed);
        }
        active_.fetch_sub(1, std::memory_order_relaxed);
    }

    // Drain remaining work with SHUTTING_DOWN after stop
    while (true) {
        WorkItem item;
        {
            std::lock_guard lock(mutex_);
            if (queue_.empty()) break;
            item = std::move(queue_.front());
            queue_.pop_front();
        }
        complete_with_error(item, "SHUTTING_DOWN", "Native runtime stopped before request executed");
    }
}

}  // namespace hades_native
