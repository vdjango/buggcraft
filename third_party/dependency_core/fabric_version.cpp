// Fabric Loader predicate semantics; see NOTICE for upstream reference/license.
#include "bugg/dependency_version.h"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <cstdint>
#include <string>
#include <vector>

namespace bugg::dependency {
namespace {
struct Semantic {
  std::vector<int> parts;
  std::optional<std::string> pre;
  bool wildcard = false;
};
std::vector<std::string_view> split(std::string_view value, char separator) {
  std::vector<std::string_view> result;
  do {
    const auto at = value.find(separator);
    result.push_back(value.substr(0, at));
    if (at == value.npos) break;
    value.remove_prefix(at + 1);
  } while (true);
  return result;
}
bool valid_text(std::string_view text) {
  return !text.empty() && text.size() <= 1024 && text.find("${") == text.npos &&
         std::all_of(text.begin(), text.end(), [](unsigned char c) { return c > 32 && c < 127; });
}
std::optional<Semantic> semantic(std::string_view value, bool wildcard) {
  if (!valid_text(value)) return {};
  Semantic result;
  const auto plus = value.find('+');
  if (plus != value.npos) {
    if (plus + 1 == value.size()) return {};
    value = value.substr(0, plus);
  }
  const auto dash = value.find('-');
  if (dash != value.npos) {
    result.pre = std::string(value.substr(dash + 1));
    if (!std::all_of(result.pre->begin(), result.pre->end(), [](unsigned char c) {
          return std::isalnum(c) || c == '-' || c == '.';
        })) return {};
    value = value.substr(0, dash);
  }
  for (auto component : split(value, '.')) {
    if (wildcard && (component == "x" || component == "X" || component == "*")) {
      if (result.pre) return {};
      if (!result.wildcard) result.parts.push_back(-1);
      result.wildcard = true;
    } else {
      int number = 0;
      auto parsed = std::from_chars(component.data(), component.data() + component.size(), number);
      if (component.empty() || component.front() < '0' || component.front() > '9' ||
          parsed.ec != std::errc{} || parsed.ptr != component.data() + component.size() ||
          number < 0 || result.wildcard) return {};
      result.parts.push_back(number);
    }
  }
  if (result.parts.size() > 64) return {};
  return result;
}
int sign(int value) { return (value > 0) - (value < 0); }
int numeric_compare(std::string_view a, std::string_view b) {
  if (a.size() != b.size()) return a.size() < b.size() ? -1 : 1;
  return sign(a.compare(b));
}
bool numeric(std::string_view value) {
  return !value.empty() && (value.size() == 1 || value.front() != '0') &&
         std::all_of(value.begin(), value.end(), [](char c) { return c >= '0' && c <= '9'; });
}
int compare(const Semantic& a, const Semantic& b) {
  for (std::size_t i = 0; i < std::max(a.parts.size(), b.parts.size()); ++i) {
    const auto av = i < a.parts.size() ? a.parts[i] : 0;
    const auto bv = i < b.parts.size() ? b.parts[i] : 0;
    if (av != bv) return av < bv ? -1 : 1;
  }
  if (!a.pre || !b.pre) return a.pre ? -1 : b.pre ? 1 : 0;
  auto left = split(*a.pre, '.'), right = split(*b.pre, '.');
  for (std::size_t i = 0; i < std::min(left.size(), right.size()); ++i) {
    const bool an = numeric(left[i]), bn = numeric(right[i]);
    int result = an && bn ? numeric_compare(left[i], right[i])
                         : an != bn ? (an ? -1 : 1) : sign(left[i].compare(right[i]));
    if (result) return result;
  }
  return left.size() < right.size() ? -1 : left.size() > right.size() ? 1 : 0;
}
std::optional<bool> term(std::string_view version, std::string_view expression) {
  std::string_view op = "=";
  for (auto candidate : {">=", "<=", ">", "<", "=", "~", "^"}) {
    if (expression.starts_with(candidate)) {
      op = candidate;
      expression.remove_prefix(op.size());
      break;
    }
  }
  if (!valid_text(expression)) return {};
  auto ref = semantic(expression, true);
  const auto current = semantic(version, false);
  if (!ref) {
    if (op == "=" || op == ">=" || op == "<=") return version == expression;
    return {};
  }
  if (ref->wildcard) {
    if (op != "=") return {};
    if (ref->parts.size() == 1) return true;
    ref->parts.pop_back();
    ref->pre = "";
    if (!current) return false;
    if (compare(*current, *ref) < 0) return false;
    for (std::size_t i = 0; i < ref->parts.size(); ++i)
      if ((i < current->parts.size() ? current->parts[i] : 0) != ref->parts[i]) return false;
    return true;
  }
  if (!current) return false;
  const auto ordering = compare(*current, *ref);
  if (op == "=") return ordering == 0;
  if (op == ">=") return ordering >= 0;
  if (op == "<=") return ordering <= 0;
  if (op == ">") return ordering > 0;
  if (op == "<") return ordering < 0;
  if (ordering < 0) return false;
  const auto count = op == "^" ? 1u : 2u;
  for (std::size_t i = 0; i < count; ++i)
    if ((i < current->parts.size() ? current->parts[i] : 0) !=
        (i < ref->parts.size() ? ref->parts[i] : 0)) return false;
  return true;
}
}  // namespace
std::optional<bool> matches_fabric(std::string_view version, std::string_view expression) {
  if (!valid_text(version) || expression.size() > 4096) return {};
  bool result = true;
  std::size_t count = 0;
  for (auto item : split(expression, ' ')) {
    if (item.empty() || item == "*") continue;
    if (++count > 64) return {};
    auto matched = term(version, item);
    if (!matched) return {};
    result &= *matched;
  }
  return result;
}
}  // namespace bugg::dependency
