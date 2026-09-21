#pragma once

#include <cstddef>
#include <map>
#include <mutex>
#include <string>

#include "hades_native/process.hpp"

namespace hades_native {
struct ServiceRecord {
    std::string id;
    long long pid = 0;
    long long creation_time = 0;
    std::string stdout_log;
    std::string stderr_log;
#ifdef _WIN32
    void* process_handle = nullptr;
    void* job_handle = nullptr;
#endif
};

class ServiceManager {
public:
    ~ServiceManager();
    Json start(const Json& params);
    Json status(const Json& params);
    Json stop(const Json& params);
    Json logs(const Json& params);
    Json probe(const Json& params);
    std::size_t active_count() const;
private:
    mutable std::mutex mutex_;
    std::map<std::string, ServiceRecord> services_;
};
}  // namespace hades_native
