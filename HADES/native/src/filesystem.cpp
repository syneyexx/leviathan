#include "hades_native/filesystem.hpp"

#include <array>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace fs = std::filesystem;
namespace hades_native {
namespace {
class Sha256 {
public:
    void update(const unsigned char* data, std::size_t length) {
        total_ += length;
        while (length) {
            const std::size_t take = std::min(length, 64U - used_);
            std::memcpy(block_.data() + used_, data, take);
            used_ += take; data += take; length -= take;
            if (used_ == 64) { transform(); used_ = 0; }
        }
    }
    std::string final() {
        const auto bits = total_ * 8;
        unsigned char one = 0x80; update(&one, 1);
        unsigned char zero = 0;
        while (used_ != 56) update(&zero, 1);
        std::array<unsigned char, 8> length{};
        for (int i = 7; i >= 0; --i) length[7 - i] = static_cast<unsigned char>(bits >> (i * 8));
        update(length.data(), length.size());
        std::ostringstream out;
        for (auto word : state_)
            for (int shift = 24; shift >= 0; shift -= 8)
                out << std::hex << std::setw(2) << std::setfill('0')
                    << ((word >> shift) & 0xffU);
        return out.str();
    }
private:
    static constexpr std::array<std::uint32_t, 64> k_ = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    static std::uint32_t rotate(std::uint32_t value, unsigned amount) { return (value >> amount) | (value << (32 - amount)); }
    void transform() {
        std::uint32_t w[64]{};
        for (int i = 0; i < 16; ++i)
            w[i] = (std::uint32_t(block_[i * 4]) << 24) | (std::uint32_t(block_[i * 4 + 1]) << 16) |
                   (std::uint32_t(block_[i * 4 + 2]) << 8) | block_[i * 4 + 3];
        for (int i = 16; i < 64; ++i) {
            const auto s0 = rotate(w[i - 15], 7) ^ rotate(w[i - 15], 18) ^ (w[i - 15] >> 3);
            const auto s1 = rotate(w[i - 2], 17) ^ rotate(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        auto a=state_[0], b=state_[1], c=state_[2], d=state_[3], e=state_[4], f=state_[5], g=state_[6], h=state_[7];
        for (int i = 0; i < 64; ++i) {
            const auto s1 = rotate(e,6) ^ rotate(e,11) ^ rotate(e,25);
            const auto choice = (e & f) ^ (~e & g);
            const auto t1 = h + s1 + choice + k_[i] + w[i];
            const auto s0 = rotate(a,2) ^ rotate(a,13) ^ rotate(a,22);
            const auto majority = (a & b) ^ (a & c) ^ (b & c);
            h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+s0+majority;
        }
        state_[0]+=a; state_[1]+=b; state_[2]+=c; state_[3]+=d; state_[4]+=e; state_[5]+=f; state_[6]+=g; state_[7]+=h;
    }
    std::array<unsigned char, 64> block_{};
    std::array<std::uint32_t, 8> state_{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    std::size_t used_ = 0, total_ = 0;
};

const fs::path& required_path(const Json& params) {
    if (!params.contains("path") || !params["path"].is_string() || params["path"].get<std::string>().empty())
        throw std::invalid_argument("path must be a non-empty string");
    static thread_local fs::path path;
    const auto text=params["path"].get<std::string>();
    path = fs::path(std::u8string(reinterpret_cast<const char8_t*>(text.data()), text.size()));
    return path;
}

long long mtime_millis(fs::file_time_type value) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(value.time_since_epoch()).count();
}

std::string utf8_string(const fs::path& path) {
    const auto encoded=path.u8string();
    return {reinterpret_cast<const char*>(encoded.data()), encoded.size()};
}
}  // namespace

Json scan_filesystem(const Json& params) {
    const auto root = required_path(params);
    if (!fs::exists(root)) throw std::runtime_error("path does not exist");
    if (!fs::is_directory(root)) throw std::invalid_argument("path must be a directory");
    const auto limit = params.value("max_entries", 10000U);
    if (limit == 0 || limit > 100000U) throw std::invalid_argument("max_entries must be between 1 and 100000");
    Json entries = Json::array();
    std::error_code ec;
    fs::recursive_directory_iterator iterator(root, fs::directory_options::skip_permission_denied, ec), end;
    for (; iterator != end && entries.size() < limit; iterator.increment(ec)) {
        if (ec) { ec.clear(); continue; }
        const auto& entry = *iterator;
        const auto status = entry.symlink_status(ec);
        if (ec) { ec.clear(); continue; }
        if (fs::is_symlink(status)) { if (entry.is_directory(ec)) iterator.disable_recursion_pending(); continue; }
        if (!fs::is_regular_file(status)) continue;
        const auto size = entry.file_size(ec); if (ec) { ec.clear(); continue; }
        const auto modified = entry.last_write_time(ec); if (ec) { ec.clear(); continue; }
        entries.push_back({{"path", utf8_string(entry.path())}, {"size", size}, {"mtime", mtime_millis(modified)},
                           {"extension", utf8_string(entry.path().extension())}});
    }
    return {{"path", utf8_string(root)}, {"entries", entries}, {"truncated", entries.size() >= limit}};
}

Json hash_file(const Json& params) {
    const auto path = required_path(params);
    if (!fs::is_regular_file(path)) throw std::invalid_argument("path must be a regular file");
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("could not open file");
    Sha256 digest;
    std::array<unsigned char, 64 * 1024> buffer{};
    while (input.read(reinterpret_cast<char*>(buffer.data()), buffer.size()) || input.gcount() > 0)
        digest.update(buffer.data(), static_cast<std::size_t>(input.gcount()));
    if (input.bad()) throw std::runtime_error("could not read file");
    return {{"path", utf8_string(path)}, {"algorithm", "sha256"}, {"sha256", digest.final()}, {"size", fs::file_size(path)}};
}

namespace {
bool match_ignore(const std::string& relative, const Json& patterns) {
    if (!patterns.is_array()) return false;
    for (const auto& pattern : patterns) {
        if (!pattern.is_string()) continue;
        const auto text = pattern.get<std::string>();
        if (text.empty()) continue;
        if (relative == text || relative.find(text) != std::string::npos) return true;
    }
    return false;
}

std::string hash_path(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("could not open file");
    Sha256 digest;
    std::array<unsigned char, 64 * 1024> buffer{};
    while (input.read(reinterpret_cast<char*>(buffer.data()), buffer.size()) || input.gcount() > 0)
        digest.update(buffer.data(), static_cast<std::size_t>(input.gcount()));
    if (input.bad()) throw std::runtime_error("could not read file");
    return digest.final();
}
}  // namespace

Json hash_many(const Json& params) {
    if (!params.contains("paths") || !params["paths"].is_array())
        throw std::invalid_argument("paths must be an array of strings");
    const auto max_files = params.value("max_files", 1000U);
    if (max_files == 0 || max_files > 10000U) throw std::invalid_argument("max_files must be between 1 and 10000");
    Json results = Json::array();
    std::size_t count = 0;
    for (const auto& item : params["paths"]) {
        if (count >= max_files) break;
        if (!item.is_string()) {
            results.push_back({{"ok", false}, {"error", "path must be a string"}});
            ++count;
            continue;
        }
        const auto text = item.get<std::string>();
        try {
            const fs::path path(std::u8string(reinterpret_cast<const char8_t*>(text.data()), text.size()));
            if (!fs::is_regular_file(path)) {
                results.push_back({{"ok", false}, {"path", text}, {"error", "not a regular file"}});
            } else {
                results.push_back({{"ok", true},
                                   {"path", text},
                                   {"algorithm", "sha256"},
                                   {"sha256", hash_path(path)},
                                   {"size", fs::file_size(path)}});
            }
        } catch (const std::exception& ex) {
            results.push_back({{"ok", false}, {"path", text}, {"error", ex.what()}});
        }
        ++count;
    }
    return {{"results", results}, {"returned", results.size()}, {"truncated", params["paths"].size() > results.size()}};
}

Json snapshot_filesystem(const Json& params) {
    const auto root = required_path(params);
    if (!fs::exists(root)) throw std::runtime_error("path does not exist");
    if (!fs::is_directory(root)) throw std::invalid_argument("path must be a directory");
    const auto limit = params.value("max_entries", 10000U);
    if (limit == 0 || limit > 100000U) throw std::invalid_argument("max_entries must be between 1 and 100000");
    const auto max_file_size = params.value("max_file_size", 32U * 1024U * 1024U);
    const bool include_hash = params.value("include_hash", false);
    const auto follow_symlinks = params.value("follow_symlinks", false);
    const auto offset = params.value("offset", 0U);
    const Json ignore = params.value("ignore", Json::array());
    Json entries = Json::array();
    Json skipped = Json::array();
    std::error_code ec;
    const auto options = follow_symlinks ? fs::directory_options::none : fs::directory_options::skip_permission_denied;
    fs::recursive_directory_iterator iterator(root, options, ec), end;
    std::size_t seen = 0;
    for (; iterator != end; iterator.increment(ec)) {
        if (ec) {
            skipped.push_back({{"path", utf8_string(iterator->path())}, {"reason", "iterator_error"}, {"error", ec.message()}});
            ec.clear();
            continue;
        }
        const auto& entry = *iterator;
        const auto relative = utf8_string(fs::relative(entry.path(), root, ec));
        if (ec) {
            ec.clear();
            continue;
        }
        if (match_ignore(relative, ignore)) {
            if (entry.is_directory(ec)) iterator.disable_recursion_pending();
            skipped.push_back({{"path", relative}, {"reason", "ignored"}});
            continue;
        }
        const auto status = entry.symlink_status(ec);
        if (ec) {
            skipped.push_back({{"path", relative}, {"reason", "stat_error"}, {"error", ec.message()}});
            ec.clear();
            continue;
        }
        if (fs::is_symlink(status) && !follow_symlinks) {
            if (entry.is_directory(ec)) iterator.disable_recursion_pending();
            skipped.push_back({{"path", relative}, {"reason", "symlink_skipped"}});
            continue;
        }
        std::string type = "other";
        if (fs::is_directory(status)) type = "directory";
        else if (fs::is_regular_file(status)) type = "file";
        else if (fs::is_symlink(status)) type = "symlink";
        if (type == "directory") continue;
        if (type != "file") {
            skipped.push_back({{"path", relative}, {"reason", "unsupported_type"}, {"type", type}});
            continue;
        }
        if (seen++ < offset) continue;
        if (entries.size() >= limit) {
            return {{"path", utf8_string(root)},
                    {"entries", entries},
                    {"skipped", skipped},
                    {"truncated", true},
                    {"offset", offset},
                    {"next_offset", offset + entries.size()}};
        }
        const auto size = entry.file_size(ec);
        if (ec) {
            skipped.push_back({{"path", relative}, {"reason", "size_error"}, {"error", ec.message()}});
            ec.clear();
            continue;
        }
        if (size > max_file_size) {
            skipped.push_back({{"path", relative}, {"reason", "max_file_size"}, {"size", size}});
            continue;
        }
        const auto modified = entry.last_write_time(ec);
        if (ec) {
            skipped.push_back({{"path", relative}, {"reason", "mtime_error"}, {"error", ec.message()}});
            ec.clear();
            continue;
        }
        Json row = {{"path", relative},
                    {"size", size},
                    {"mtime", mtime_millis(modified)},
                    {"extension", utf8_string(entry.path().extension())},
                    {"type", type}};
        if (include_hash) {
            try {
                row["sha256"] = hash_path(entry.path());
            } catch (const std::exception& ex) {
                row["hash_error"] = ex.what();
            }
        }
        entries.push_back(std::move(row));
    }
    // Deterministic ordering when feasible
    std::sort(entries.begin(), entries.end(), [](const Json& a, const Json& b) {
        return a.value("path", "") < b.value("path", "");
    });
    return {{"path", utf8_string(root)},
            {"entries", entries},
            {"skipped", skipped},
            {"truncated", false},
            {"offset", offset},
            {"returned", entries.size()}};
}

Json search_repository(const Json& params) {
    const auto root = required_path(params);
    if (!params.contains("query") || !params["query"].is_string() || params["query"].get<std::string>().empty())
        throw std::invalid_argument("query must be a non-empty string");
    const auto query = params["query"].get<std::string>();
    const auto max_matches = params.value("max_matches", 200U);
    const auto max_file_bytes = params.value("max_file_bytes", 1024U * 1024U);
    if (max_matches == 0 || max_matches > 5000U) throw std::invalid_argument("max_matches must be between 1 and 5000");
    if (!fs::is_directory(root)) throw std::invalid_argument("path must be a directory");
    Json matches = Json::array();
    std::error_code ec;
    fs::recursive_directory_iterator iterator(root, fs::directory_options::skip_permission_denied, ec), end;
    for (; iterator != end && matches.size() < max_matches; iterator.increment(ec)) {
        if (ec) {
            ec.clear();
            continue;
        }
        const auto& entry = *iterator;
        const auto status = entry.symlink_status(ec);
        if (ec || fs::is_symlink(status) || !fs::is_regular_file(status)) {
            if (fs::is_symlink(status) && entry.is_directory(ec)) iterator.disable_recursion_pending();
            ec.clear();
            continue;
        }
        const auto size = entry.file_size(ec);
        if (ec || size == 0 || size > max_file_bytes) {
            ec.clear();
            continue;
        }
        std::ifstream input(entry.path(), std::ios::binary);
        if (!input) continue;
        std::string content((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
        // Skip obvious binary
        if (content.find('\0') != std::string::npos) continue;
        std::size_t pos = 0;
        unsigned line = 1;
        std::size_t line_start = 0;
        while (pos < content.size() && matches.size() < max_matches) {
            const auto found = content.find(query, pos);
            if (found == std::string::npos) break;
            while (line_start < found) {
                if (content[line_start] == '\n') ++line;
                ++line_start;
            }
            const auto line_end = content.find('\n', found);
            const auto excerpt_begin = content.rfind('\n', found);
            const auto start = excerpt_begin == std::string::npos ? 0 : excerpt_begin + 1;
            const auto end_pos = line_end == std::string::npos ? content.size() : line_end;
            matches.push_back({{"path", utf8_string(fs::relative(entry.path(), root))},
                               {"line", line},
                               {"column", static_cast<unsigned>(found - start + 1)},
                               {"excerpt", content.substr(start, end_pos - start)}});
            pos = found + std::max<std::size_t>(query.size(), 1);
        }
    }
    return {{"path", utf8_string(root)},
            {"query", query},
            {"matches", matches},
            {"returned", matches.size()},
            {"truncated", matches.size() >= max_matches}};
}
}  // namespace hades_native
