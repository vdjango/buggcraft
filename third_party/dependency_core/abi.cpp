#include "bugg/dependency_version.h"
#include "bugg/dependency_check.h"
#include <cstring>
#include <cstdlib>

#ifdef _WIN32
#define BUGG_EXPORT __declspec(dllexport)
#else
#define BUGG_EXPORT __attribute__((visibility("default")))
#endif

extern "C" {
BUGG_EXPORT const char *bugg_dependency_version() { return "bugg-dependency-core-v1"; }
/// -2 = unsupported/invalid; otherwise -1/0/+1 using Maven ComparableVersion.
BUGG_EXPORT int bugg_dependency_compare_maven(const char *left, const char *right) {
  if (!left || !right) return -2;
  try {
    return bugg::dependency::compare_maven(left, right).value_or(-2);
  } catch (...) {
    return -2;
  }
}
/// -1 = unsupported, 0 = does not match, 1 = matches. Never throws across C
/// ABI.
BUGG_EXPORT int bugg_dependency_matches(const char *version, const char *expression,
                                        const char *dialect) {
  if (!version || !expression || !dialect) return -1;
  try {
    const auto result = std::string_view(dialect) == "maven" ? bugg::dependency::matches_maven(version, expression)
                       : std::string_view(dialect) == "fabric" ? bugg::dependency::matches_fabric(version, expression)
                       : std::nullopt;
    return result ? static_cast<int>(*result) : -1;
  } catch (...) {
    return -1;
  }
}
/// Owned UTF-8 result; caller must use bugg_dependency_free. Null = invalid input.
BUGG_EXPORT char* bugg_dependency_evaluate(const char* input, int solve) {
  if (!input) return nullptr;
  try {
    auto result = solve ? bugg::dependency::solve_json(input) : bugg::dependency::check_json(input);
    auto output = static_cast<char*>(std::malloc(result.size() + 1));
    if (output) std::memcpy(output, result.c_str(), result.size() + 1);
    return output;
  } catch (...) { return nullptr; }
}
BUGG_EXPORT void bugg_dependency_free(char* output) { std::free(output); }
BUGG_EXPORT char* bugg_dependency_metadata(const char* input) {
  if (!input) return nullptr;
  try {
    auto result = bugg::dependency::metadata_json(input);
    auto output = static_cast<char*>(std::malloc(result.size() + 1));
    if (output) std::memcpy(output, result.c_str(), result.size() + 1);
    return output;
  } catch (...) { return nullptr; }
}
}
