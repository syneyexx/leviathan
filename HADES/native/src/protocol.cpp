#include "hades_native/protocol.hpp"

#include "hades_native/version.hpp"

namespace hades_native {
bool validate_request(const Json& request, RpcError& error) {
    if (!request.is_object()) {
        error = {"INVALID_REQUEST", "Request must be a JSON object"};
        return false;
    }
    if (!request.contains("version") || !request["version"].is_number_integer() ||
        request["version"].get<int>() != kProtocolVersion) {
        error = {"UNSUPPORTED_VERSION", "Only protocol version 1 is supported",
                 {{"expected", kProtocolVersion},
                  {"got", request.contains("version") ? request["version"] : Json(nullptr)}}};
        return false;
    }
    if (!request.contains("id") || (!request["id"].is_string() && !request["id"].is_number())) {
        error = {"INVALID_REQUEST", "Request id must be a string or number"};
        return false;
    }
    if (!request.contains("method") || !request["method"].is_string() || request["method"].get<std::string>().empty()) {
        error = {"INVALID_REQUEST", "Request method is required"};
        return false;
    }
    if (request.contains("params") && !request["params"].is_object()) {
        error = {"INVALID_PARAMS", "Request params must be an object"};
        return false;
    }
    return true;
}

Json success_response(const Json& id, Json result, const WorkMeta& meta) {
    Json meta_obj = {
        {"duration_ms", meta.duration_ms},
        {"queue_ms", meta.queue_ms},
        {"worker_id", meta.worker_id},
    };
    if (meta.truncated) meta_obj["truncated"] = true;
    return {{"version", kProtocolVersion},
            {"id", id},
            {"ok", true},
            {"result", std::move(result)},
            {"meta", std::move(meta_obj)}};
}

Json error_response(const Json& id, const RpcError& error, const WorkMeta& meta) {
    Json body = {{"version", kProtocolVersion},
                 {"id", id},
                 {"ok", false},
                 {"error", {{"code", error.code}, {"message", error.message}, {"details", error.details}}}};
    if (meta.duration_ms || meta.queue_ms || meta.worker_id) {
        body["meta"] = {{"duration_ms", meta.duration_ms},
                        {"queue_ms", meta.queue_ms},
                        {"worker_id", meta.worker_id}};
    }
    return body;
}

Json exception_to_error(const std::exception& exception) {
    return {{"code", "INTERNAL_ERROR"}, {"message", exception.what()}, {"details", Json::object()}};
}

std::optional<long long> request_deadline_ms(const Json& params) {
    if (!params.is_object()) return std::nullopt;
    if (params.contains("deadline_ms") && params["deadline_ms"].is_number_integer()) {
        const auto value = params["deadline_ms"].get<long long>();
        if (value > 0) return value;
    }
    // RPC-level wall deadline distinct from process timeout_ms
    if (params.contains("rpc_timeout_ms") && params["rpc_timeout_ms"].is_number_integer()) {
        const auto value = params["rpc_timeout_ms"].get<long long>();
        if (value > 0) return value;
    }
    return std::nullopt;
}
}  // namespace hades_native
