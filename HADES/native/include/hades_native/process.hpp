#pragma once

#include <atomic>
#include <map>
#include <mutex>
#include <string>
#include <vector>

#include "hades_native/protocol.hpp"

namespace hades_native {
struct ProcessRequest {
    std::string executable;
    std::vector<std::string> argv;
    std::string cwd;
    std::map<std::string, std::string> env;
    unsigned int timeout_ms = 0;
    std::size_t max_stdout_bytes = 1024 * 1024;
    std::size_t max_stderr_bytes = 1024 * 1024;
};

struct ProcessResult {
    long long pid = 0;
    int exit_code = -1;
    bool timed_out = false;
    bool cancelled = false;
    std::string stdout_data;
    std::string stderr_data;
    bool stdout_truncated = false;
    bool stderr_truncated = false;
};

struct RunningProcess {
    std::atomic<long long> pid{0};
    std::atomic_bool cancel_requested{false};
#ifdef _WIN32
    // process.run owns and closes these handles. process.cancel may only inspect /
    // terminate through them while holding state_mutex; it never closes them.
    std::mutex state_mutex;
    void* process_handle = nullptr;
    void* job_handle = nullptr;
#endif
};

ProcessRequest parse_process_request(const Json& params);
ProcessResult run_process(const ProcessRequest& request, RunningProcess& running);
bool cancel_process(RunningProcess& running, std::string& error);
}  // namespace hades_native
