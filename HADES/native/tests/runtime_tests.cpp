#include <atomic>
#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <thread>
#include <vector>

#include "hades_native/runtime.hpp"

namespace fs = std::filesystem;

int main() {
    hades_native::Runtime runtime;
    const auto call = [&runtime](const std::string& method, hades_native::Json params = hades_native::Json::object()) {
        static std::atomic_uint id{0};
        const auto request_id = id.fetch_add(1, std::memory_order_relaxed) + 1;
        return runtime.dispatch({{"version", 1}, {"id", request_id}, {"method", method}, {"params", std::move(params)}});
    };

    auto hello = call("runtime.hello");
    assert(hello["ok"] && hello["result"]["version"] == "0.2.0");

    const auto malformed = runtime.dispatch({{"version", "one"}, {"id", "bad"}, {"method", "runtime.health"}, {"params", {}}});
    assert(!malformed["ok"] && malformed["error"]["code"] == "UNSUPPORTED_VERSION");

    const auto bad_params = runtime.dispatch({{"version", 1}, {"id", 2}, {"method", "runtime.health"}, {"params", "nope"}});
    assert(!bad_params["ok"] && bad_params["error"]["code"] == "INVALID_PARAMS");

    const auto unknown = call("does.not.exist");
    assert(!unknown["ok"] && unknown["error"]["code"] == "UNKNOWN_METHOD");

    const auto root = fs::temp_directory_path() / "hades-native-runtime-tests";
    fs::remove_all(root);
    fs::create_directories(root);
    const auto file = root / "sample.txt";
    {
        std::ofstream out(file, std::ios::binary);
        out << "abc";
    }
    auto hash = call("fs.hash", {{"path", file.string()}});
    assert(hash["ok"] && hash["result"]["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");

    auto hash_many = call("fs.hash_many", {{"paths", {file.string(), (root / "missing.txt").string()}}});
    assert(hash_many["ok"] && hash_many["result"]["results"].size() == 2);
    assert(hash_many["result"]["results"][0]["ok"] == true);
    assert(hash_many["result"]["results"][1]["ok"] == false);

    auto snapshot = call("fs.snapshot", {{"path", root.string()}, {"include_hash", true}});
    assert(snapshot["ok"] && snapshot["result"]["entries"].size() >= 1);

    auto search = call("repo.search", {{"path", root.string()}, {"query", "abc"}});
    assert(search["ok"] && search["result"]["matches"].size() >= 1);

    auto scan = call("fs.scan", {{"path", root.string()}});
    assert(scan["ok"] && scan["result"]["entries"].size() == 1 && scan["result"]["entries"][0]["extension"] == ".txt");

    auto caps = call("runtime.capabilities");
    assert(caps["ok"]);
    assert(caps["result"]["bounded_executor"] == true);
    assert(caps["result"]["process_tree_kill"] == true);
    // Honest: memory_limit is not implemented
    assert(caps["result"]["memory_limit"] == false);
#ifdef _WIN32
    assert(caps["result"]["job_objects"] == true);
#else
    assert(caps["result"]["job_objects"] == false);
#endif

#ifdef _WIN32
    auto run = call("process.run", {{"executable", "cmd.exe"}, {"argv", {"/C", "echo", "native-ok"}}, {"timeout_ms", 3000}});
#else
    auto run = call("process.run", {{"executable", "/bin/sh"}, {"argv", {"-c", "printf native-ok"}}, {"timeout_ms", 3000}});
#endif
    assert(run["ok"] && run["result"]["exit_code"] == 0);
    assert(run["result"]["stdout"].get<std::string>().find("native-ok") != std::string::npos);

    // Oversized stdout truncation
#ifdef _WIN32
    auto truncated = call("process.run",
                          {{"executable", "cmd.exe"},
                           {"argv", {"/C", "echo", "0123456789abcdef"}},
                           {"timeout_ms", 3000},
                           {"max_stdout_bytes", 4}});
#else
    auto truncated = call("process.run",
                          {{"executable", "/bin/sh"},
                           {"argv", {"-c", "printf '0123456789abcdef'"}},
                           {"timeout_ms", 3000},
                           {"max_stdout_bytes", 4}});
#endif
    assert(truncated["ok"] && truncated["result"]["stdout_truncated"] == true);
    assert(truncated["result"]["stdout"].get<std::string>().size() == 4);

    // Invalid executable
#ifdef _WIN32
    auto bad_exe = call("process.run", {{"executable", "C:\\definitely\\missing\\hades_nope.exe"}, {"argv", hades_native::Json::array()}, {"timeout_ms", 1000}});
#else
    auto bad_exe = call("process.run", {{"executable", "/definitely/missing/hades_nope"}, {"argv", hades_native::Json::array()}, {"timeout_ms", 1000}});
#endif
    assert(!bad_exe["ok"]);

    // Unicode path + spaces
    const auto unicode_dir = root / u8"sp ace-δ";
    fs::create_directories(unicode_dir);
    const auto unicode_file = unicode_dir / u8"f ile.txt";
    {
        std::ofstream out(unicode_file, std::ios::binary);
        out << "hello-unicode";
    }
    const auto unicode_u8 = unicode_file.u8string();
    const auto unicode_path = unicode_u8.empty()
        ? unicode_file.string()
        : std::string(reinterpret_cast<const char*>(unicode_u8.data()), unicode_u8.size());
    auto unicode_hash = call("fs.hash", {{"path", unicode_path}});
    assert(unicode_hash["ok"]);

    const auto timeout_started = std::chrono::steady_clock::now();
    auto timeout = call("process.run", {{"executable",
#ifdef _WIN32
                                         "cmd.exe"
#else
                                         "/bin/sh"
#endif
                                        },
                                        {"argv",
#ifdef _WIN32
                                         {"/C", "ping -n 3 127.0.0.1 > nul"}
#else
                                         {"-c", "sleep 2"}
#endif
                                        },
                                        {"timeout_ms", 20}});
    const auto timeout_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - timeout_started).count();
    assert(timeout["ok"] && timeout["result"]["timed_out"]);
    assert(timeout_elapsed < 1500);  // termination must not wait for the natural child lifetime

    // Concurrent cancel race: wait until the job is registered, then cancel it.
    std::string cancel_job = "cancel-race-1";
    hades_native::Json cancelled_run;
    const auto cancel_started = std::chrono::steady_clock::now();
    std::thread runner([&] {
        cancelled_run = call("process.run", {{"executable",
#ifdef _WIN32
                              "cmd.exe"
#else
                              "/bin/sh"
#endif
                             },
                             {"argv",
#ifdef _WIN32
                              {"/C", "ping -n 5 127.0.0.1 > nul"}
#else
                              {"-c", "sleep 5"}
#endif
                             },
                             {"timeout_ms", 10000},
                             {"job_id", cancel_job}});
    });
    bool job_visible = false;
    for (int attempt = 0; attempt < 100; ++attempt) {
        auto health = call("runtime.health");
        if (health["ok"] && health["result"]["active_jobs"].get<std::size_t>() > 0) {
            job_visible = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    assert(job_visible);
    auto cancel = call("process.cancel", {{"job_id", cancel_job}});
    assert(cancel["ok"] && cancel["result"]["cancel_requested"] == true);
    // Duplicate cancel is idempotent whether cleanup has already removed the job or not.
    auto cancel2 = call("process.cancel", {{"job_id", cancel_job}});
    assert(cancel2["ok"]);
    auto cancel_unknown = call("process.cancel", {{"job_id", "never-existed"}});
    assert(cancel_unknown["ok"] && cancel_unknown["result"]["idempotent"] == true);
    runner.join();
    const auto cancel_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - cancel_started).count();
    assert(cancelled_run["ok"] && cancelled_run["result"]["cancelled"] == true);
    assert(cancel_elapsed < 2000);  // a cancelled ping/sleep must not run to natural completion

    // Child process tree (shell spawning child)
#ifdef _WIN32
    auto tree = call("process.run", {{"executable", "cmd.exe"}, {"argv", {"/C", "cmd.exe /C echo tree-ok"}}, {"timeout_ms", 5000}, {"job_id", "tree-1"}});
#else
    auto tree = call("process.run", {{"executable", "/bin/sh"}, {"argv", {"-c", "/bin/sh -c 'printf tree-ok'"}}, {"timeout_ms", 5000}, {"job_id", "tree-1"}});
#endif
    assert(tree["ok"] && tree["result"]["stdout"].get<std::string>().find("tree-ok") != std::string::npos);

    auto service = call("service.start", {{"id", "test-service"},
                                          {"executable",
#ifdef _WIN32
                                           "cmd.exe"
#else
                                           "/bin/sh"
#endif
                                          },
                                          {"argv",
#ifdef _WIN32
                                           {"/C", "echo service-ok & ping -n 3 127.0.0.1 > nul"}
#else
                                           {"-c", "printf service-ok; sleep 2"}
#endif
                                          },
                                          {"log_dir", root.string()}});
    assert(service["ok"] && service["result"]["running"]);
    hades_native::Json logs;
    bool saw_service_output = false;
    for (int attempt = 0; attempt < 50; ++attempt) {
        logs = call("service.logs", {{"id", "test-service"}});
        if (logs["ok"] && logs["result"]["stdout"].get<std::string>().find("service-ok") != std::string::npos) {
            saw_service_output = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    assert(saw_service_output);
    auto probe = call("service.probe", {{"id", "test-service"}, {"creation_time", service["result"]["creation_time"]}});
    assert(probe["ok"] && probe["result"]["identity_matches"] && probe["result"]["running"]);
    auto stop = call("service.stop", {{"id", "test-service"}});
    assert(stop["ok"] && stop["result"]["stopped"]);

    // Repeated shutdown
    auto shutdown1 = call("runtime.shutdown");
    assert(shutdown1["ok"]);
    auto shutdown2 = call("runtime.shutdown");
    assert(shutdown2["ok"]);
    auto after_shutdown = call("runtime.health");
    (void)after_shutdown;
    // health may still respond; process.run should fail
    auto blocked = call("process.run", {{"executable",
#ifdef _WIN32
                                         "cmd.exe"
#else
                                         "/bin/echo"
#endif
                                        },
                                        {"argv",
#ifdef _WIN32
                                         {"/C", "echo", "nope"}
#else
                                         {"nope"}
#endif
                                        },
                                        {"timeout_ms", 1000}});
    assert(!blocked["ok"] && blocked["error"]["code"] == "SHUTTING_DOWN");

    auto metrics = call("system.metrics");
    // system.metrics after shutdown should fail.
    assert(!metrics["ok"]);

    fs::remove_all(root);
    return 0;
}
