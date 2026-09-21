#include "hades_native/metrics.hpp"

#include <chrono>
#include <mutex>

#ifdef _WIN32
#include <windows.h>
#else
#include <sys/sysinfo.h>
#include <unistd.h>
#include <fstream>
#endif

namespace hades_native {
namespace {
struct CpuSample { unsigned long long idle=0, total=0; bool valid=false; };
CpuSample sample_cpu() {
    CpuSample sample;
#ifdef _WIN32
    FILETIME idle{}, kernel{}, user{};
    if (GetSystemTimes(&idle, &kernel, &user)) {
        const auto to_u64=[](FILETIME filetime) { return (static_cast<unsigned long long>(filetime.dwHighDateTime)<<32) | filetime.dwLowDateTime; };
        sample.idle=to_u64(idle); sample.total=to_u64(kernel)+to_u64(user); sample.valid=true;
    }
#else
    std::ifstream input("/proc/stat"); std::string label; unsigned long long fields[8]{};
    if (input >> label && label == "cpu") {
        for (auto& field : fields) input >> field;
        sample.idle=fields[3]+fields[4]; for (const auto field : fields) sample.total+=field; sample.valid=true;
    }
#endif
    return sample;
}
}

Json system_metrics(unsigned long long active_jobs) {
    static std::mutex mutex; static CpuSample previous;
    const auto current=sample_cpu(); Json cpu_percent=nullptr;
    { std::lock_guard lock(mutex);
      if (current.valid && previous.valid && current.total > previous.total) {
          const auto busy=(current.total-current.idle)-(previous.total-previous.idle);
          cpu_percent=100.0*static_cast<double>(busy)/static_cast<double>(current.total-previous.total);
      }
      previous=current;
    }
    Json result={{"active_jobs", active_jobs}, {"cpu_percent", cpu_percent}};
#ifdef _WIN32
    MEMORYSTATUSEX memory{sizeof(memory)};
    if (GlobalMemoryStatusEx(&memory)) {
        result["memory"]={{"total_bytes", memory.ullTotalPhys}, {"available_bytes", memory.ullAvailPhys},
                          {"used_bytes", memory.ullTotalPhys-memory.ullAvailPhys}};
    }
    result["uptime_ms"]=static_cast<unsigned long long>(GetTickCount64());
    result["logical_cpu_count"]=GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
#else
    struct sysinfo info{};
    if (sysinfo(&info) == 0) {
        const auto unit=static_cast<unsigned long long>(info.mem_unit);
        result["memory"]={{"total_bytes", static_cast<unsigned long long>(info.totalram)*unit},
                          {"available_bytes", static_cast<unsigned long long>(info.freeram)*unit},
                          {"used_bytes", static_cast<unsigned long long>(info.totalram-info.freeram)*unit}};
        result["uptime_ms"]=static_cast<unsigned long long>(info.uptime)*1000;
    }
    result["logical_cpu_count"]=static_cast<unsigned int>(sysconf(_SC_NPROCESSORS_ONLN));
#endif
    return result;
}
}  // namespace hades_native
