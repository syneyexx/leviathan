#pragma once

#include "hades_native/protocol.hpp"

namespace hades_native {
Json scan_filesystem(const Json& params);
Json hash_file(const Json& params);
Json hash_many(const Json& params);
Json snapshot_filesystem(const Json& params);
Json search_repository(const Json& params);
}  // namespace hades_native
