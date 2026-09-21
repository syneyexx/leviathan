#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

namespace hades_native {
using Json = nlohmann::json;

inline constexpr std::size_t kMaxRequestBytes = 8ULL * 1024ULL * 1024ULL;
inline constexpr std::size_t kMaxResponseBytes = 16ULL * 1024ULL * 1024ULL;

struct RpcError {
    std::string code;
    std::string message;
    Json details = Json::object();
};

/// Per-request execution metadata attached to responses.
struct WorkMeta {
    long long queue_ms = 0;
    long long duration_ms = 0;
    unsigned worker_id = 0;
    bool truncated = false;
};

bool validate_request(const Json& request, RpcError& error);
Json success_response(const Json& id, Json result, const WorkMeta& meta);
Json error_response(const Json& id, const RpcError& error, const WorkMeta& meta = {});
Json exception_to_error(const std::exception& exception);

/// Parse optional RPC-level deadline from params (deadline_ms from now, or absolute not supported).
std::optional<long long> request_deadline_ms(const Json& params);

}  // namespace hades_native
