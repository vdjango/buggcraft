// Maven nested-item comparison adapted from Apache Maven 3.9.9.
// SPDX-License-Identifier: Apache-2.0. See NOTICE and LICENSE-APACHE-2.0.txt.
#include <algorithm>
#include <array>
#include <cctype>
#include <memory>
#include <string>
#include <vector>

#include "bugg/dependency_version.h"

namespace bugg::dependency {
namespace {
enum class Kind { Number, String, List };
struct Item {
  Kind kind;
  std::string value;
  std::vector<std::unique_ptr<Item>> children;
};
std::string trim(std::string_view value) {
  auto first = value.find_first_not_of(" \t\r\n");
  if (first == value.npos) return {};
  return std::string(value.substr(first, value.find_last_not_of(" \t\r\n") - first + 1));
}
bool valid(std::string_view value) {
  return !value.empty() && value.size() <= 1024 &&
         std::none_of(value.begin(), value.end(), [](unsigned char c) {
           return c <= 32 || c >= 127 || c == '[' || c == ']' || c == '(' || c == ')' || c == ',' ||
                  c == '$' || c == '{' || c == '}';
         });
}
int compare_text(std::string_view left, std::string_view right) {
  const auto result = left.compare(right);
  return (result > 0) - (result < 0);
}
std::string qualifier(const std::string &value) {
  constexpr std::array<std::string_view, 7> names{"alpha",    "beta", "milestone", "rc",
                                                  "snapshot", "",     "sp"};
  auto found = std::find(names.begin(), names.end(), value);
  return found == names.end() ? "7-" + value : std::to_string(found - names.begin());
}
int compare(const Item *left, const Item *right) {
  if (!left) return right ? -compare(right, nullptr) : 0;
  if (!right) {
    if (left->kind == Kind::Number) return left->value == "0" ? 0 : 1;
    if (left->kind == Kind::String) return compare_text(qualifier(left->value), "5");
    for (const auto &child : left->children)
      if (auto result = compare(child.get(), nullptr)) return result;
    return 0;
  }
  if (left->kind == Kind::Number) {
    if (right->kind != Kind::Number) return 1;
    if (left->value.size() != right->value.size())
      return left->value.size() > right->value.size() ? 1 : -1;
    return compare_text(left->value, right->value);
  }
  if (left->kind == Kind::String) {
    return right->kind == Kind::String
               ? compare_text(qualifier(left->value), qualifier(right->value))
               : -1;
  }
  if (right->kind != Kind::List) return right->kind == Kind::Number ? -1 : 1;
  const auto size = std::max(left->children.size(), right->children.size());
  for (size_t i = 0; i < size; ++i) {
    auto *l = i < left->children.size() ? left->children[i].get() : nullptr;
    auto *r = i < right->children.size() ? right->children[i].get() : nullptr;
    if (auto result = compare(l, r)) return result;
  }
  return 0;
}
std::unique_ptr<Item> item(bool digit, std::string value, bool followed = false) {
  if (digit) {
    auto first = value.find_first_not_of('0');
    value = first == value.npos ? "0" : value.substr(first);
  } else {
    if (followed && value.size() == 1) {
      if (value == "a") value = "alpha";
      if (value == "b") value = "beta";
      if (value == "m") value = "milestone";
    }
    if (value == "ga" || value == "final" || value == "release") value.clear();
    if (value == "cr") value = "rc";
  }
  return std::make_unique<Item>(Item{digit ? Kind::Number : Kind::String, std::move(value), {}});
}
std::unique_ptr<Item> parse(std::string_view input) {
  if (!valid(input)) return {};
  std::string value(input);
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  auto root = std::make_unique<Item>(Item{Kind::List, {}, {}});
  Item *list = root.get();
  std::vector<Item *> stack{list};
  const auto nest = [&] {
    list->children.push_back(std::make_unique<Item>(Item{Kind::List, {}, {}}));
    list = list->children.back().get();
    stack.push_back(list);
  };
  bool digit = false;
  size_t start = 0;
  for (size_t i = 0; i < value.size(); ++i) {
    const auto c = value[i];
    if (c == '.' || c == '-') {
      list->children.push_back(i == start ? item(true, "0")
                                          : item(digit, value.substr(start, i - start)));
      start = i + 1;
      if (c == '-') nest();
    } else if (c >= '0' && c <= '9') {
      if (!digit && i > start) {
        if (!list->children.empty()) nest();
        list->children.push_back(item(false, value.substr(start, i - start), true));
        start = i;
        nest();
      }
      digit = true;
    } else {
      if (digit && i > start) {
        list->children.push_back(item(true, value.substr(start, i - start)));
        start = i;
        nest();
      }
      digit = false;
    }
  }
  if (value.size() > start) {
    if (!digit && !list->children.empty()) nest();
    list->children.push_back(item(digit, value.substr(start)));
  }
  for (auto current = stack.rbegin(); current != stack.rend(); ++current) {
    auto &children = (*current)->children;
    for (size_t index = children.size(); index > 0;) {
      --index;
      const auto &child = children[index];
      const bool empty = child->kind == Kind::List     ? child->children.empty()
                         : child->kind == Kind::Number ? child->value == "0"
                                                       : qualifier(child->value) == "5";
      if (empty)
        children.erase(children.begin() + index);
      else if (child->kind != Kind::List)
        break;
    }
  }
  return root;
}
}  // namespace
std::optional<int> compare_maven(std::string_view left, std::string_view right) {
  auto l = parse(left), r = parse(right);
  if (!l || !r) return {};
  return compare(l.get(), r.get());
}
std::optional<bool> matches_maven(std::string_view version, std::string_view expression) {
  auto candidate = parse(version);
  if (!candidate || expression.size() > 4096) return {};
  auto remaining = trim(expression);
  if (remaining.empty() || remaining == "*") return true;
  if (remaining.find_first_of("<>~^=") != remaining.npos) return {};
  // A bare Maven version is a recommendation with an unrestricted range;
  // exact constraints are written [version]. Do not interpret it as equality.
  if (remaining.front() != '[' && remaining.front() != '(')
    return parse(remaining) ? std::optional(true) : std::nullopt;
  bool result = false;
  size_t ranges = 0;
  while (!remaining.empty()) {
    if (++ranges > 64 || (remaining.front() != '[' && remaining.front() != '(')) return {};
    const auto close = remaining.find_first_of(")]");
    if (close == remaining.npos) return {};
    const bool lower_inclusive = remaining.front() == '[';
    const bool upper_inclusive = remaining[close] == ']';
    const auto bounds = remaining.substr(1, close - 1);
    const auto comma = bounds.find(',');
    if (comma == bounds.npos) {
      if (!lower_inclusive || !upper_inclusive) return {};
      auto exact = parse(trim(bounds));
      if (!exact) return {};
      result |= compare(candidate.get(), exact.get()) == 0;
    } else {
      if (bounds.find(',', comma + 1) != bounds.npos) return {};
      auto lower = trim(bounds.substr(0, comma)), upper = trim(bounds.substr(comma + 1));
      auto l = lower.empty() ? nullptr : parse(lower);
      auto r = upper.empty() ? nullptr : parse(upper);
      if ((!lower.empty() && !l) || (!upper.empty() && !r) || (lower.empty() && lower_inclusive) ||
          (upper.empty() && upper_inclusive))
        return {};
      if (l && r) {
        const auto order = compare(l.get(), r.get());
        if (order > 0 || (order == 0 && (!lower_inclusive || !upper_inclusive))) return {};
      }
      const auto low = l ? compare(candidate.get(), l.get()) : 1;
      const auto high = r ? compare(candidate.get(), r.get()) : -1;
      result |=
          (low > 0 || low == 0 && lower_inclusive) && (high < 0 || high == 0 && upper_inclusive);
    }
    remaining = trim(remaining.substr(close + 1));
    if (!remaining.empty()) {
      if (remaining.front() != ',') return {};
      remaining = trim(remaining.substr(1));
      if (remaining.empty()) return {};
    }
  }
  return result;
}
}  // namespace bugg::dependency
