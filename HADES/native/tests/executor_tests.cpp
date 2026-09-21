#include <atomic>
#include <cassert>
#include <chrono>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "hades_native/executor.hpp"
#include "hades_native/runtime.hpp"

int main() {
    hades_native::Runtime runtime;
    std::mutex responses_mu;
    std::vector<hades_native::Json> responses;
    std::atomic_bool block_gate{false};
    std::atomic_int blocking_started{0};

    hades_native::BoundedExecutor executor(
        2, 4,
        [&](const hades_native::Json& request, const hades_native::WorkMeta& meta) {
            if (request.value("method", "") == "test.block") {
                blocking_started.fetch_add(1, std::memory_order_release);
                while (block_gate.load(std::memory_order_acquire)) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(1));
                }
                auto forwarded = request;
                forwarded["method"] = "runtime.health";
                forwarded["params"] = hades_native::Json::object();
                return runtime.dispatch(forwarded, meta);
            }
            return runtime.dispatch(request, meta);
        },
        [&](const hades_native::Json& response) {
            std::lock_guard lock(responses_mu);
            responses.push_back(response);
        });

    auto make_item = [](std::string id, std::string method = "runtime.health") {
        hades_native::WorkItem item;
        item.id = id;
        item.method = method;
        item.request = {{"version", 1}, {"id", id}, {"method", method}, {"params", hades_native::Json::object()}};
        return item;
    };

    // Deterministic queue saturation: occupy both workers first, then fill all
    // four queue slots. A seventh submission must be rejected as QueueFull.
    block_gate.store(true, std::memory_order_release);
    assert(executor.try_submit(make_item("block-a", "test.block")) == hades_native::SubmitResult::Accepted);
    assert(executor.try_submit(make_item("block-b", "test.block")) == hades_native::SubmitResult::Accepted);
    for (int attempt = 0; attempt < 500 && blocking_started.load(std::memory_order_acquire) < 2; ++attempt) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(blocking_started.load(std::memory_order_acquire) == 2);

    for (int i = 0; i < 4; ++i) {
        assert(executor.try_submit(make_item("queued-" + std::to_string(i))) == hades_native::SubmitResult::Accepted);
    }
    assert(executor.try_submit(make_item("overflow")) == hades_native::SubmitResult::QueueFull);
    block_gate.store(false, std::memory_order_release);

    // Wait for drain.
    for (int i = 0; i < 500; ++i) {
        auto stats = executor.stats();
        if (stats.queued == 0 && stats.active == 0) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }

    {
        std::lock_guard lock(responses_mu);
        assert(responses.size() == 6);
        for (const auto& response : responses) {
            assert(response.contains("ok"));
            if (response["ok"]) {
                assert(response.contains("meta"));
                assert(response["meta"].contains("queue_ms"));
                assert(response["meta"].contains("worker_id"));
            }
        }
        responses.clear();
    }

    // Deterministic queued-deadline test: occupy both workers again, enqueue an
    // already-expired item, then release the workers. The late item must be
    // rejected by the executor before its handler runs.
    block_gate.store(true, std::memory_order_release);
    const int blocking_before = blocking_started.load(std::memory_order_acquire);
    assert(executor.try_submit(make_item("deadline-block-a", "test.block")) == hades_native::SubmitResult::Accepted);
    assert(executor.try_submit(make_item("deadline-block-b", "test.block")) == hades_native::SubmitResult::Accepted);
    for (int attempt = 0; attempt < 500 && blocking_started.load(std::memory_order_acquire) < blocking_before + 2; ++attempt) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(blocking_started.load(std::memory_order_acquire) == blocking_before + 2);

    auto late = make_item("late");
    late.deadline = std::chrono::steady_clock::now() - std::chrono::milliseconds(1);
    assert(executor.try_submit(std::move(late)) == hades_native::SubmitResult::Accepted);
    block_gate.store(false, std::memory_order_release);

    for (int i = 0; i < 500; ++i) {
        auto stats = executor.stats();
        if (stats.queued == 0 && stats.active == 0) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }

    {
        std::lock_guard lock(responses_mu);
        bool saw_deadline = false;
        for (const auto& response : responses) {
            if (response.value("id", hades_native::Json{}) == hades_native::Json("late")) {
                saw_deadline = true;
                assert(response["ok"] == false);
                assert(response["error"]["code"] == "DEADLINE_EXCEEDED");
            }
        }
        assert(saw_deadline);
    }

    executor.request_shutdown();
    executor.join();
    const auto final_stats = executor.stats();
    assert(final_stats.worker_count == 0);  // joined/cleared
    assert(final_stats.accepted >= 9);
    assert(final_stats.rejected_full >= 1);
    assert(final_stats.deadline_exceeded >= 1);
    return 0;
}
