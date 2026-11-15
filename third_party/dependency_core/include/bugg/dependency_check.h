#pragma once
#include <string>
#include <string_view>

namespace bugg::dependency {
/// Pure bounded facts checker and candidate search. JSON in/out uses
/// bugg-dependency-check-v1; no filesystem/network, immutable caller input.
/// Throws on malformed input; unknown syntax is an explicit issue. Call on a worker.
std::string check_json(std::string_view input);
std::string solve_json(std::string_view input);
/// Parse bounded, already-read metadata members without executing the artifact.
/// Returns per-container facts and explicitly declared nested member paths.
std::string metadata_json(std::string_view input);
/// Select among caller-provided Java majors against the declaration checker,
/// including upper bounds/conflicts. Input: check + minimum_java/candidates.
/// No download/JVM execution; returns major or null and structured issues.
std::string select_java_json(std::string_view input);
}  // namespace bugg::dependency
