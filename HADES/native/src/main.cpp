#include <chrono>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>

#include "hades_native/executor.hpp"
#include "hades_native/runtime.hpp"

namespace {
std::size_t parse_size_arg(const char* value, std::size_t fallback) {
    if (!value || !*value) return fallback;
    char* end = nullptr;
    const auto parsed = std::strtoull(value, &end, 10);
    if (end == value || parsed == 0) return fallback;
    return static_cast<std::size_t>(parsed);
}
}  // namespace

int main(int argc, char** argv) {
    std::size_t workers = hades_native::resolve_worker_count_from_env();
    std::size_t queue_capacity = hades_native::resolve_queue_capacity_from_env();
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i] ? argv[i] : "";
        if ((arg == "--workers" || arg == "-w") && i + 1 < argc) {
            workers = parse_size_arg(argv[++i], workers);
        } else if ((arg == "--queue" || arg == "-q") && i + 1 < argc) {
            queue_capacity = parse_size_arg(argv[++i], queue_capacity);
        }
    }

    hades_native::Runtime runtime;
    std::mutex output_mutex;
    auto writer = [&output_mutex](const hades_native::Json& response) {
        std::lock_guard lock(output_mutex);
        // Keep protocol on stdout only; truncate only if somehow enormous.
        auto dumped = response.dump();
        if (dumped.size() > hades_native::kMaxResponseBytes) {
            const auto id = response.contains("id") ? response["id"] : hades_native::Json(nullptr);
            dumped = hades_native::error_response(id, {"OUTPUT_LIMIT", "Response exceeded maximum size"}).dump();
        }
        std::cout << dumped << '\n' << std::flush;
    };

    hades_native::BoundedExecutor* executor_ptr = nullptr;
    hades_native::BoundedExecutor executor(
        workers, queue_capacity,
        [&runtime](const hades_native::Json& request, const hades_native::WorkMeta& meta) {
            return runtime.dispatch(request, meta);
        },
        writer);
    executor_ptr = &executor;
    runtime.set_executor_stats_provider([executor_ptr] {
        const auto s = executor_ptr->stats();
        return hades_native::ExecutorStatsView{
            s.worker_count,
            s.queue_capacity,
            s.queued,
            s.active,
            s.accepted,
            s.rejected_full,
            s.completed,
            s.cancelled,
            s.deadline_exceeded,
        };
    });

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        if (line.size() > hades_native::kMaxRequestBytes) {
            writer(hades_native::error_response(nullptr, {"INVALID_REQUEST", "Request exceeds maximum message size"}));
            continue;
        }
        try {
            auto request = hades_native::Json::parse(line, nullptr, true, true);
            const hades_native::Json request_id =
                request.contains("id") ? request["id"] : hades_native::Json(nullptr);
            hades_native::WorkItem item;
            item.id = request_id;
            item.method = request.value("method", "");
            const auto params = request.value("params", hades_native::Json::object());
            if (const auto deadline_ms = hades_native::request_deadline_ms(params)) {
                item.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(*deadline_ms);
            }
            item.request = std::move(request);

            const auto submit = executor.try_submit(std::move(item));
            if (submit == hades_native::SubmitResult::QueueFull) {
                writer(hades_native::error_response(
                    request_id,
                    {"QUEUE_FULL", "Native executor queue is saturated",
                     {{"queue_capacity", static_cast<int>(queue_capacity)}}}));
            } else if (submit == hades_native::SubmitResult::ShuttingDown) {
                writer(hades_native::error_response(request_id, {"SHUTTING_DOWN", "Native runtime is shutting down"}));
            }
            if (runtime.shutdown_requested()) break;
        } catch (const std::exception& error) {
            writer({{"version", 1},
                    {"id", nullptr},
                    {"ok", false},
                    {"error",
                     {{"code", "PARSE_ERROR"}, {"message", error.what()}, {"details", hades_native::Json::object()}}}});
        }
    }

    executor.request_shutdown();
    executor.join();
    std::cerr << "hades_native_runtime stopped\n";
    return 0;
}
