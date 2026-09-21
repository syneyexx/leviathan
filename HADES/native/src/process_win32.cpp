#include "hades_native/process.hpp"

#include <chrono>
#include <stdexcept>
#include <thread>

#ifdef _WIN32
#include <windows.h>

#include <algorithm>
#include <sstream>

namespace hades_native {
namespace {
std::wstring utf8_to_wide(const std::string& value) {
    if (value.empty()) return {};
    const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), nullptr, 0);
    if (!count) throw std::invalid_argument("invalid UTF-8 process parameter");
    std::wstring result(count, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), result.data(), count);
    return result;
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
    for (const auto& [key, value] : overrides) values[utf8_to_wide(key)]=utf8_to_wide(value);
    std::vector<wchar_t> block;
    for (const auto& [key, value] : values) {
        block.insert(block.end(), key.begin(), key.end()); block.push_back(L'=');
        block.insert(block.end(), value.begin(), value.end()); block.push_back(L'\0');
    }
    block.push_back(L'\0'); return block;
}
std::wstring quote_arg(const std::string& text) {
    const auto value = utf8_to_wide(text);
    if (value.find_first_of(L" \t\"") == std::wstring::npos) return value;
    std::wstring output = L"\""; unsigned slashes = 0;
    for (wchar_t character : value) {
        if (character == L'\\') { ++slashes; continue; }
        if (character == L'"') output.append(slashes * 2 + 1, L'\\');
        else output.append(slashes, L'\\');
        output += character; slashes = 0;
    }
    output.append(slashes * 2, L'\\'); output += L'"';
    return output;
}
void append_pipe(HANDLE pipe, std::string& target, std::size_t maximum, bool& truncated) {
    DWORD available = 0;
    while (PeekNamedPipe(pipe, nullptr, 0, nullptr, &available, nullptr) && available) {
        char buffer[8192]; DWORD read = 0;
        if (!ReadFile(pipe, buffer, std::min<DWORD>(available, sizeof(buffer)), &read, nullptr) || !read) break;
        const auto remaining = target.size() < maximum ? maximum - target.size() : 0;
        const auto kept = std::min<std::size_t>(remaining, read);
        target.append(buffer, kept);
        truncated = truncated || kept < read;
    }
}

bool terminate_registered_process(RunningProcess& running, std::string& error) {
    std::lock_guard lock(running.state_mutex);
    const auto job = static_cast<HANDLE>(running.job_handle);
    const auto process = static_cast<HANDLE>(running.process_handle);
    if (job && TerminateJobObject(job, 1)) return true;
    if (process && TerminateProcess(process, 1)) return true;
    error = "process is no longer running";
    return false;
}

void close_registered_handles(RunningProcess& running) noexcept {
    std::lock_guard lock(running.state_mutex);
    if (running.process_handle) CloseHandle(static_cast<HANDLE>(running.process_handle));
    if (running.job_handle) CloseHandle(static_cast<HANDLE>(running.job_handle));
    running.process_handle = nullptr;
    running.job_handle = nullptr;
}
}

ProcessRequest parse_process_request(const Json& params) {
    ProcessRequest request;
    if (!params.contains("executable") || !params["executable"].is_string() || params["executable"].get<std::string>().empty())
        throw std::invalid_argument("executable must be a non-empty string");
    request.executable = params["executable"].get<std::string>();
    if (params.contains("argv")) {
        if (!params["argv"].is_array()) throw std::invalid_argument("argv must be an array");
        for (const auto& value : params["argv"]) { if (!value.is_string()) throw std::invalid_argument("argv values must be strings"); request.argv.push_back(value.get<std::string>()); }
    }
    if (params.contains("cwd")) { if (!params["cwd"].is_string()) throw std::invalid_argument("cwd must be a string"); request.cwd = params["cwd"].get<std::string>(); }
    if (params.contains("env")) {
        if (!params["env"].is_object()) throw std::invalid_argument("env must be an object");
        for (auto it=params["env"].begin(); it!=params["env"].end(); ++it) { if (!it.value().is_string()) throw std::invalid_argument("env values must be strings"); request.env.emplace(it.key(), it.value().get<std::string>()); }
    }
    request.timeout_ms = params.value("timeout_ms", 0U);
    request.max_stdout_bytes = params.value("max_stdout_bytes", 1024U * 1024U);
    request.max_stderr_bytes = params.value("max_stderr_bytes", 1024U * 1024U);
    if (request.max_stdout_bytes > 64U * 1024U * 1024U || request.max_stderr_bytes > 64U * 1024U * 1024U)
        throw std::invalid_argument("output limits cannot exceed 64 MiB");
    return request;
}

ProcessResult run_process(const ProcessRequest& request, RunningProcess& running) {
    SECURITY_ATTRIBUTES attributes{sizeof(attributes), nullptr, TRUE};
    HANDLE out_read=nullptr, out_write=nullptr, err_read=nullptr, err_write=nullptr;
    if (!CreatePipe(&out_read, &out_write, &attributes, 0) || !SetHandleInformation(out_read, HANDLE_FLAG_INHERIT, 0) ||
        !CreatePipe(&err_read, &err_write, &attributes, 0) || !SetHandleInformation(err_read, HANDLE_FLAG_INHERIT, 0))
        throw std::runtime_error("CreatePipe failed");
    std::wstring command = quote_arg(request.executable);
    for (const auto& argument : request.argv) command += L" " + quote_arg(argument);
    STARTUPINFOW startup{sizeof(startup)}; startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE); startup.hStdOutput = out_write; startup.hStdError = err_write;
    PROCESS_INFORMATION info{};
    std::wstring cwd;
    if (!request.cwd.empty()) cwd=utf8_to_wide(request.cwd);
    auto environment=environment_block(request.env);
    const DWORD flags = CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED;
    if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE, flags,
                        environment.data(), cwd.empty() ? nullptr : cwd.c_str(), &startup, &info)) {
        CloseHandle(out_read); CloseHandle(out_write); CloseHandle(err_read); CloseHandle(err_write);
        throw std::runtime_error("CreateProcessW failed: " + std::to_string(GetLastError()));
    }
    CloseHandle(out_write); CloseHandle(err_write);

    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        const bool configured = SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) != FALSE;
        const bool assigned = configured && AssignProcessToJobObject(job, info.hProcess) != FALSE;
        if (!assigned) {
            CloseHandle(job);
            job = nullptr;
        }
    }

    running.pid.store(static_cast<long long>(info.dwProcessId), std::memory_order_release);
    {
        std::lock_guard lock(running.state_mutex);
        running.process_handle = info.hProcess;
        running.job_handle = job;
    }

    bool started = false;
    if (running.cancel_requested.load(std::memory_order_acquire)) {
        std::string ignored;
        terminate_registered_process(running, ignored);
    } else {
        const DWORD resume_result = ResumeThread(info.hThread);
        if (resume_result == static_cast<DWORD>(-1)) {
            TerminateProcess(info.hProcess, 1);
            WaitForSingleObject(info.hProcess, 5000);
            CloseHandle(info.hThread);
            CloseHandle(out_read); CloseHandle(err_read);
            close_registered_handles(running);
            throw std::runtime_error("ResumeThread failed: " + std::to_string(GetLastError()));
        }
        started = true;
    }
    CloseHandle(info.hThread);

    ProcessResult result; result.pid = running.pid.load(std::memory_order_acquire);
    const auto began = std::chrono::steady_clock::now();
    bool termination_sent = running.cancel_requested.load(std::memory_order_acquire);
    while (WaitForSingleObject(info.hProcess, 10) == WAIT_TIMEOUT) {
        append_pipe(out_read, result.stdout_data, request.max_stdout_bytes, result.stdout_truncated);
        append_pipe(err_read, result.stderr_data, request.max_stderr_bytes, result.stderr_truncated);
        const bool cancelled = running.cancel_requested.load(std::memory_order_acquire);
        const bool timed_out = request.timeout_ms &&
            std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count() >= request.timeout_ms;
        if (!termination_sent && (cancelled || timed_out)) {
            result.cancelled = cancelled;
            result.timed_out = !cancelled && timed_out;
            std::string ignored;
            terminate_registered_process(running, ignored);
            termination_sent = true;
        }
    }
    append_pipe(out_read, result.stdout_data, request.max_stdout_bytes, result.stdout_truncated);
    append_pipe(err_read, result.stderr_data, request.max_stderr_bytes, result.stderr_truncated);
    DWORD code=0; GetExitCodeProcess(info.hProcess, &code); result.exit_code = static_cast<int>(code);
    result.cancelled = result.cancelled || running.cancel_requested.load(std::memory_order_acquire);
    if (!started && result.cancelled) result.timed_out = false;
    CloseHandle(out_read); CloseHandle(err_read);
    close_registered_handles(running);
    return result;
}

bool cancel_process(RunningProcess& running, std::string& error) {
    running.cancel_requested.store(true, std::memory_order_release);
    return terminate_registered_process(running, error);
}
}  // namespace hades_native

#else
#include <cerrno>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstdlib>
#include <stdexcept>

namespace hades_native {
namespace {
void set_nonblocking(int fd) {
    const int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) throw std::runtime_error("could not configure process pipe");
}
void drain(int& fd, std::string& target, std::size_t maximum, bool& truncated) {
    std::array<char, 8192> buffer{};
    while (fd >= 0) {
        const auto count = read(fd, buffer.data(), buffer.size());
        if (count > 0) {
            const auto remaining = target.size() < maximum ? maximum - target.size() : 0;
            const auto kept = std::min<std::size_t>(remaining, static_cast<std::size_t>(count));
            target.append(buffer.data(), kept); truncated = truncated || kept < static_cast<std::size_t>(count);
        } else if (count == 0) { close(fd); fd = -1; }
        else if (errno == EAGAIN || errno == EWOULDBLOCK) return;
        else if (errno == EINTR) continue;
        else { close(fd); fd = -1; }
    }
}
}

ProcessRequest parse_process_request(const Json& params) {
    ProcessRequest request;
    if (!params.contains("executable") || !params["executable"].is_string() || params["executable"].get<std::string>().empty())
        throw std::invalid_argument("executable must be a non-empty string");
    request.executable = params["executable"].get<std::string>();
    if (params.contains("argv")) {
        if (!params["argv"].is_array()) throw std::invalid_argument("argv must be an array");
        for (const auto& item : params["argv"]) { if (!item.is_string()) throw std::invalid_argument("argv values must be strings"); request.argv.push_back(item.get<std::string>()); }
    }
    if (params.contains("cwd")) { if (!params["cwd"].is_string()) throw std::invalid_argument("cwd must be a string"); request.cwd=params["cwd"].get<std::string>(); }
    if (params.contains("env")) {
        if (!params["env"].is_object()) throw std::invalid_argument("env must be an object");
        for (auto it=params["env"].begin(); it != params["env"].end(); ++it) { if (!it.value().is_string()) throw std::invalid_argument("env values must be strings"); request.env.emplace(it.key(), it.value().get<std::string>()); }
    }
    request.timeout_ms=params.value("timeout_ms", 0U);
    request.max_stdout_bytes=params.value("max_stdout_bytes", 1024U*1024U);
    request.max_stderr_bytes=params.value("max_stderr_bytes", 1024U*1024U);
    if (request.max_stdout_bytes > 64U*1024U*1024U || request.max_stderr_bytes > 64U*1024U*1024U) throw std::invalid_argument("output limits cannot exceed 64 MiB");
    return request;
}

ProcessResult run_process(const ProcessRequest& request, RunningProcess& running) {
    int out_pipe[2], err_pipe[2];
    if (pipe(out_pipe) || pipe(err_pipe)) throw std::runtime_error("pipe creation failed");
    const pid_t child=fork();
    if (child < 0) throw std::runtime_error("fork failed");
    if (child == 0) {
        setpgid(0, 0);
        dup2(out_pipe[1], STDOUT_FILENO); dup2(err_pipe[1], STDERR_FILENO);
        close(out_pipe[0]); close(out_pipe[1]); close(err_pipe[0]); close(err_pipe[1]);
        if (!request.cwd.empty() && chdir(request.cwd.c_str()) != 0) _exit(127);
        for (const auto& [key, value] : request.env) setenv(key.c_str(), value.c_str(), 1);
        std::vector<char*> argv; argv.reserve(request.argv.size()+2);
        argv.push_back(const_cast<char*>(request.executable.c_str()));
        for (const auto& argument : request.argv) argv.push_back(const_cast<char*>(argument.c_str()));
        argv.push_back(nullptr); execvp(request.executable.c_str(), argv.data()); _exit(127);
    }
    (void)setpgid(child, child);  // close the parent/cancel race; child repeats this defensively
    close(out_pipe[1]); close(err_pipe[1]); set_nonblocking(out_pipe[0]); set_nonblocking(err_pipe[0]);
    running.pid.store(child, std::memory_order_release); ProcessResult result; result.pid=child;
    const auto started=std::chrono::steady_clock::now(); bool killed=false; int status=0;
    while (true) {
        drain(out_pipe[0], result.stdout_data, request.max_stdout_bytes, result.stdout_truncated);
        drain(err_pipe[0], result.stderr_data, request.max_stderr_bytes, result.stderr_truncated);
        const auto waited=waitpid(child, &status, WNOHANG);
        if (waited == child) break;
        if (waited < 0) throw std::runtime_error("waitpid failed");
        const auto elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
        if (!killed && (running.cancel_requested.load(std::memory_order_acquire) || (request.timeout_ms && elapsed >= request.timeout_ms))) {
            result.cancelled=running.cancel_requested.load(std::memory_order_acquire); result.timed_out=!result.cancelled; kill(-child, SIGKILL); killed=true;
        }
        pollfd descriptors[2]={{out_pipe[0], POLLIN, 0}, {err_pipe[0], POLLIN, 0}}; poll(descriptors, 2, 10);
    }
    while (out_pipe[0]>=0 || err_pipe[0]>=0) { drain(out_pipe[0], result.stdout_data, request.max_stdout_bytes, result.stdout_truncated); drain(err_pipe[0], result.stderr_data, request.max_stderr_bytes, result.stderr_truncated); if(out_pipe[0]>=0 || err_pipe[0]>=0) std::this_thread::sleep_for(std::chrono::milliseconds(1)); }
    result.exit_code=WIFEXITED(status) ? WEXITSTATUS(status) : (WIFSIGNALED(status) ? 128+WTERMSIG(status) : -1);
    result.cancelled = result.cancelled || running.cancel_requested.load(std::memory_order_acquire);
    return result;
}

bool cancel_process(RunningProcess& running, std::string& error) {
    running.cancel_requested.store(true, std::memory_order_release);
    const auto pid = running.pid.load(std::memory_order_acquire);
    if (pid > 0 && kill(-static_cast<pid_t>(pid), SIGKILL) == 0) return true;
    error="process is no longer running"; return false;
}
}  // namespace hades_native
#endif
