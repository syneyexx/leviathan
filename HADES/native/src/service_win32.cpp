#include "hades_native/service.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#else
#include <csignal>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace fs = std::filesystem;
namespace hades_native {
namespace {
std::string required_id(const Json& params) {
    const auto id = params.value("id", "");
    if (id.empty() || id.size() > 128 || id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-") != std::string::npos)
        throw std::invalid_argument("id must contain only letters, digits, dot, underscore, or hyphen");
    return id;
}
fs::path utf8_path(const std::string& value) {
    return fs::path(std::u8string(reinterpret_cast<const char8_t*>(value.data()), value.size()));
}
long long now_millis() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
}
std::string read_tail(const std::string& filename, std::size_t maximum) {
    std::ifstream input(filename, std::ios::binary);
    if (!input) return {};
    input.seekg(0, std::ios::end);
    const auto size = input.tellg();
    if (size > static_cast<std::streamoff>(maximum)) input.seekg(-static_cast<std::streamoff>(maximum), std::ios::end);
    else input.seekg(0);
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
#ifdef _WIN32
std::wstring wide(const std::string& value) {
    if (value.empty()) return {};
    const auto length=MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), nullptr, 0);
    if (!length) throw std::invalid_argument("invalid UTF-8 process parameter");
    std::wstring result(length, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), result.data(), length);
    return result;
}
// Named quote_arg (not quoted) to avoid ADL collision with std::quoted from <iomanip>.
std::wstring quote_arg(const std::string& raw) {
    const auto value=wide(raw); if (value.find_first_of(L" \t\"") == std::wstring::npos) return value;
    std::wstring result=L"\""; unsigned backslashes=0;
    for (const auto character : value) {
        if (character == L'\\') { ++backslashes; continue; }
        result.append(backslashes * (character == L'"' ? 2 : 1) + (character == L'"' ? 1 : 0), L'\\');
        result+=character; backslashes=0;
    }
    result.append(backslashes * 2, L'\\'); return result + L'"';
}
std::vector<wchar_t> environment_block(const std::map<std::string, std::string>& overrides) {
    std::map<std::wstring, std::wstring> values;
    const auto raw=GetEnvironmentStringsW();
    if (raw) {
        for (auto item=raw; *item; item+=wcslen(item)+1) {
            const std::wstring line=item; const auto separator=line.find(L'=', 1);
            if (separator != std::wstring::npos) values[line.substr(0, separator)]=line.substr(separator+1);
        }
        FreeEnvironmentStringsW(raw);
    }
    for (const auto& [key, value] : overrides) values[wide(key)]=wide(value);
    std::vector<wchar_t> block;
    for (const auto& [key, value] : values) { block.insert(block.end(), key.begin(), key.end()); block.push_back(L'='); block.insert(block.end(), value.begin(), value.end()); block.push_back(L'\0'); }
    block.push_back(L'\0'); return block;
}
long long creation_time(HANDLE process) {
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(process, &created, &exited, &kernel, &user)) return now_millis();
    return static_cast<long long>((static_cast<unsigned long long>(created.dwHighDateTime)<<32) | created.dwLowDateTime);
}
#endif
bool alive(const ServiceRecord& service) {
#ifdef _WIN32
    return service.process_handle && WaitForSingleObject(static_cast<HANDLE>(service.process_handle), 0) == WAIT_TIMEOUT;
#else
    return service.pid > 0 && kill(static_cast<pid_t>(service.pid), 0) == 0;
#endif
}
void terminate(ServiceRecord& service) {
#ifdef _WIN32
    const auto process = static_cast<HANDLE>(service.process_handle);
    const auto job = static_cast<HANDLE>(service.job_handle);
    bool terminated_via_job = false;
    bool terminated = false;
    if (job) {
        terminated_via_job = TerminateJobObject(job, 1) != FALSE;
        terminated = terminated_via_job;
    }
    if (!terminated && process) terminated = TerminateProcess(process, 1) != FALSE;
    if (terminated) {
        // A job object becomes signaled only after all of its associated processes
        // are gone. Waiting on the job (when available) makes stopped=true mean the
        // whole service tree has released inherited log handles, not just the root.
        const auto wait_target = terminated_via_job ? job : process;
        if (wait_target) WaitForSingleObject(wait_target, 5000);
    }
    if (process) CloseHandle(process);
    if (job) CloseHandle(job);
    service.process_handle=nullptr; service.job_handle=nullptr;
#else
    if (service.pid > 0) { kill(-static_cast<pid_t>(service.pid), SIGTERM); }
#endif
}
}

ServiceManager::~ServiceManager() {
    std::lock_guard lock(mutex_);
    for (auto& [_, service] : services_) terminate(service);
}

Json ServiceManager::start(const Json& params) {
    const auto id=required_id(params);
    auto request=parse_process_request(params);
    std::lock_guard lock(mutex_);
    if (const auto existing=services_.find(id); existing != services_.end() && alive(existing->second))
        throw std::runtime_error("service already running");
    if (const auto existing=services_.find(id); existing != services_.end()) { terminate(existing->second); services_.erase(existing); }
    const fs::path log_dir=params.contains("log_dir") ? utf8_path(params["log_dir"].get<std::string>()) : fs::temp_directory_path() / "hades-native" / "services";
    fs::create_directories(log_dir);
    ServiceRecord service; service.id=id; service.creation_time=now_millis();
    service.stdout_log=(log_dir / (id + ".stdout.log")).string(); service.stderr_log=(log_dir / (id + ".stderr.log")).string();
#ifdef _WIN32
    SECURITY_ATTRIBUTES attributes{sizeof(attributes), nullptr, TRUE};
    const auto output=CreateFileW((log_dir / (id + ".stdout.log")).wstring().c_str(), FILE_APPEND_DATA, FILE_SHARE_READ|FILE_SHARE_WRITE,
                                  &attributes, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    const auto errors=CreateFileW((log_dir / (id + ".stderr.log")).wstring().c_str(), FILE_APPEND_DATA, FILE_SHARE_READ|FILE_SHARE_WRITE,
                                  &attributes, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (output == INVALID_HANDLE_VALUE || errors == INVALID_HANDLE_VALUE) {
        if (output != INVALID_HANDLE_VALUE) CloseHandle(output); if (errors != INVALID_HANDLE_VALUE) CloseHandle(errors);
        throw std::runtime_error("could not open service logs");
    }
    std::wstring command=quote_arg(request.executable);
    for (const auto& argument : request.argv) command += L" " + quote_arg(argument);
    std::wstring cwd; if (!request.cwd.empty()) cwd=wide(request.cwd);
    auto environment=environment_block(request.env);
    STARTUPINFOW startup{sizeof(startup)}; startup.dwFlags=STARTF_USESTDHANDLES;
    startup.hStdInput=GetStdHandle(STD_INPUT_HANDLE); startup.hStdOutput=output; startup.hStdError=errors;
    PROCESS_INFORMATION process{};
    const auto flags=CREATE_NO_WINDOW|CREATE_UNICODE_ENVIRONMENT|CREATE_SUSPENDED;
    if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE, flags, environment.data(),
                        cwd.empty() ? nullptr : cwd.c_str(), &startup, &process)) {
        CloseHandle(output); CloseHandle(errors); throw std::runtime_error("CreateProcessW failed: " + std::to_string(GetLastError()));
    }
    CloseHandle(output); CloseHandle(errors);

    HANDLE job=CreateJobObjectW(nullptr, nullptr);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        const bool configured=SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) != FALSE;
        const bool assigned=configured && AssignProcessToJobObject(job, process.hProcess) != FALSE;
        if (!assigned) { CloseHandle(job); job=nullptr; }
    }

    const auto resume=ResumeThread(process.hThread);
    if (resume == static_cast<DWORD>(-1)) {
        const auto error=GetLastError();
        TerminateProcess(process.hProcess, 1);
        WaitForSingleObject(process.hProcess, 5000);
        CloseHandle(process.hThread); CloseHandle(process.hProcess); if (job) CloseHandle(job);
        throw std::runtime_error("ResumeThread failed: " + std::to_string(error));
    }
    CloseHandle(process.hThread);
    service.pid=static_cast<long long>(process.dwProcessId); service.process_handle=process.hProcess; service.job_handle=job;
    service.creation_time=creation_time(process.hProcess);
#else
    const pid_t child=fork();
    if (child < 0) throw std::runtime_error("fork failed");
    if (child == 0) {
        setpgid(0, 0);
        const int out=open(service.stdout_log.c_str(), O_WRONLY|O_CREAT|O_APPEND, 0600);
        const int err=open(service.stderr_log.c_str(), O_WRONLY|O_CREAT|O_APPEND, 0600);
        if (out < 0 || err < 0) _exit(127);
        dup2(out, STDOUT_FILENO); dup2(err, STDERR_FILENO); close(out); close(err);
        if (!request.cwd.empty() && chdir(request.cwd.c_str()) != 0) _exit(127);
        for (const auto& [key, value] : request.env) setenv(key.c_str(), value.c_str(), 1);
        std::vector<char*> argv; argv.push_back(const_cast<char*>(request.executable.c_str()));
        for (const auto& argument : request.argv) argv.push_back(const_cast<char*>(argument.c_str()));
        argv.push_back(nullptr); execvp(request.executable.c_str(), argv.data()); _exit(127);
    }
    (void)setpgid(child, child);
    service.pid=child;
#endif
    const auto result=Json{{"id", id}, {"pid", service.pid}, {"creation_time", service.creation_time},
                           {"stdout_log", service.stdout_log}, {"stderr_log", service.stderr_log}, {"running", true}};
    services_.emplace(id, std::move(service)); return result;
}

Json ServiceManager::status(const Json& params) {
    const auto id=required_id(params); std::lock_guard lock(mutex_);
    const auto it=services_.find(id); if (it==services_.end()) throw std::runtime_error("unknown service");
    return {{"id", id}, {"pid", it->second.pid}, {"creation_time", it->second.creation_time}, {"running", alive(it->second)},
            {"stdout_log", it->second.stdout_log}, {"stderr_log", it->second.stderr_log}};
}

Json ServiceManager::stop(const Json& params) {
    const auto id=required_id(params); std::lock_guard lock(mutex_);
    const auto it=services_.find(id); if (it==services_.end()) throw std::runtime_error("unknown service");
    const bool was_running=alive(it->second); terminate(it->second);
#ifndef _WIN32
    if (it->second.pid > 0) waitpid(static_cast<pid_t>(it->second.pid), nullptr, WNOHANG);
#endif
    return {{"id", id}, {"stopped", true}, {"was_running", was_running}};
}

Json ServiceManager::logs(const Json& params) {
    const auto id=required_id(params); const auto stream=params.value("stream", "both");
    const auto maximum=params.value("max_bytes", 65536U);
    if (maximum > 4U*1024U*1024U) throw std::invalid_argument("max_bytes cannot exceed 4 MiB");
    std::lock_guard lock(mutex_); const auto it=services_.find(id); if (it==services_.end()) throw std::runtime_error("unknown service");
    Json result={{"id", id}};
    if (stream == "stdout" || stream == "both") result["stdout"]=read_tail(it->second.stdout_log, maximum);
    if (stream == "stderr" || stream == "both") result["stderr"]=read_tail(it->second.stderr_log, maximum);
    if (stream != "stdout" && stream != "stderr" && stream != "both") throw std::invalid_argument("stream must be stdout, stderr, or both");
    return result;
}

Json ServiceManager::probe(const Json& params) {
    const auto id=required_id(params); std::lock_guard lock(mutex_);
    const auto it=services_.find(id); if (it==services_.end()) throw std::runtime_error("unknown service");
    const auto expected=params.value("creation_time", it->second.creation_time);
    const bool matches=expected == it->second.creation_time;
    return {{"id", id}, {"pid", it->second.pid}, {"creation_time", it->second.creation_time},
            {"identity_matches", matches}, {"running", matches && alive(it->second)}};
}

std::size_t ServiceManager::active_count() const {
    std::lock_guard lock(mutex_);
    return services_.size();
}
}  // namespace hades_native
