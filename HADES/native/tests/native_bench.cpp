#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "hades_native/executor.hpp"
#include "hades_native/runtime.hpp"

namespace {
double percentile(std::vector<double> values, double p) {
    if (values.empty()) return 0;
    std::sort(values.begin(), values.end());
    const double idx = (p / 100.0) * static_cast<double>(values.size() - 1);
    const auto lo = static_cast<std::size_t>(std::floor(idx));
    const auto hi = static_cast<std::size_t>(std::ceil(idx));
    if (lo == hi) return values[lo];
    return values[lo] + (values[hi] - values[lo]) * (idx - static_cast<double>(lo));
}
}  // namespace

int main(int argc, char** argv) {
    const int count = argc > 1 ? std::max(1, std::atoi(argv[1])) : 1000;
    hades_native::Runtime runtime;
    std::mutex mu;
    std::vector<double> latencies_ms;
    latencies_ms.reserve(static_cast<std::size_t>(count));
    std::atomic<int> done{0};

    hades_native::BoundedExecutor executor(
        0, 0,
        [&runtime](const hades_native::Json& request, const hades_native::WorkMeta& meta) {
            return runtime.dispatch(request, meta);
        },
        [&](const hades_native::Json& response) {
            (void)response;
            done.fetch_add(1);
        });

    const auto wall_start = std::chrono::steady_clock::now();
    for (int i = 0; i < count; ++i) {
        const auto t0 = std::chrono::steady_clock::now();
        hades_native::WorkItem item;
        item.id = i;
        item.method = "runtime.health";
        item.request = {{"version", 1}, {"id", i}, {"method", "runtime.health"}, {"params", hades_native::Json::object()}};
        while (executor.try_submit(std::move(item)) != hades_native::SubmitResult::Accepted) {
            item.request = {{"version", 1}, {"id", i}, {"method", "runtime.health"}, {"params", hades_native::Json::object()}};
            item.id = i;
            item.method = "runtime.health";
            std::this_thread::sleep_for(std::chrono::microseconds(50));
        }
        const auto submit_ms =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        std::lock_guard lock(mu);
        latencies_ms.push_back(submit_ms);
    }
    while (done.load() < count) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    const auto wall_ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - wall_start).count();

    const auto stats = executor.stats();
    executor.request_shutdown();
    executor.join();

    std::vector<double> copy = latencies_ms;
    const double throughput = wall_ms > 0 ? (1000.0 * count / wall_ms) : 0;
    std::cout << "native_bench health_rpc count=" << count << " wall_ms=" << wall_ms
              << " throughput_rps=" << throughput << " submit_p50_ms=" << percentile(copy, 50)
              << " submit_p95_ms=" << percentile(copy, 95) << " submit_p99_ms=" << percentile(copy, 99)
              << " workers=" << stats.worker_count << " rejected_full=" << stats.rejected_full
              << " completed=" << stats.completed << '\n';
    return 0;
}
