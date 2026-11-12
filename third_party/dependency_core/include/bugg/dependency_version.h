#ifndef BUGG_DEPENDENCY_VERSION_H_
#define BUGG_DEPENDENCY_VERSION_H_

#include <optional>
#include <string_view>

namespace bugg::dependency {
/// Pure bounded version dialect rules shared by native clients and source
/// workers. nullopt means unsupported/invalid, never equivalent to a satisfied
/// constraint.
std::optional<int> compare_maven(std::string_view left, std::string_view right);
std::optional<bool> matches_maven(std::string_view version, std::string_view expression);
/// Fabric Loader predicates (space = AND; arrays are OR in the facts adapter).
/// Unsupported/malformed syntax returns nullopt, never a compatibility success.
std::optional<bool> matches_fabric(std::string_view version, std::string_view expression);
}  // namespace bugg::dependency
#endif
