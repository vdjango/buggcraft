#include <algorithm>
#include <functional>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>

#include "bugg/dependency_check.h"
#include "bugg/dependency_version.h"
#include "json.hpp"
#include "runtime_rules.h"

namespace bugg::dependency {
namespace {
using Json = nlohmann::json;
struct Provider {
  std::string artifact, version, identity;
};
bool client_side(const Json& value) {
  return value.is_null() || value == "" || value == "*" || value == "BOTH" || value == "CLIENT" ||
         value == "client";
}
std::optional<bool> matches(const std::string& version, const Json& expression,
                            const std::string& dialect) {
  if (expression.is_array()) {
    if (expression.empty() || expression.size() > 128) return {};
    bool unknown = false;
    for (const auto& item : expression) {
      auto result = matches(version, item, dialect);
      if (result && *result) return true;
      unknown |= !result.has_value();
    }
    return unknown ? std::nullopt : std::optional(false);
  }
  if (!expression.is_null() && !expression.is_string()) return {};
  if (version.empty()) return {};
  const auto text = expression.is_null() ? std::string{} : expression.get<std::string>();
  return dialect == "fabric" ? matches_fabric(version, text) : matches_maven(version, text);
}
Json issue(std::string code, const std::string& artifact, std::string mod = {},
           std::string target = {}, Json required = nullptr, std::string severity = "error",
           std::string evidence = {}) {
  const auto id = code + "/" + artifact + "/" + mod + "/" + target + "/" + required.dump();
  return {{"id", id},
          {"code", code},
          {"artifact", artifact},
          {"mod_id", mod},
          {"target_id", target},
          {"required", required},
          {"severity", severity},
          {"evidence", evidence}};
}
bool active_format(const std::string& format, const std::string& loader, bool has_neo) {
  if (loader == "neoforge") return format == "neoforge" || (!has_neo && format == "forge_toml");
  if (loader == "forge") return format == "forge_toml";
  if (loader == "fabric") return format == "fabric";
  return false;
}
Json check(const Json& input) {
  const auto& environment = input.at("environment");
  const auto loader = environment.at("loader").get<std::string>();
  const auto& artifacts = input.at("artifacts");
  if (!artifacts.is_array() || artifacts.size() > 4096)
    throw std::invalid_argument("artifact_budget");
  Json issues = Json::array();
  std::map<std::string, std::vector<Provider>> providers;
  auto builtin = [&](const std::string& id, const std::string& version) {
    if (!version.empty()) providers[id].push_back({"environment", version, "environment"});
  };
  builtin("minecraft", environment.value("minecraft", ""));
  builtin(loader == "fabric"  ? "fabricloader"
          : loader == "quilt" ? "quilt_loader"
                              : loader,
          environment.value("loader_version", ""));
  builtin("java", environment.value("java", ""));
  struct Declaration {
    std::string artifact;
    Json mod;
  };
  std::vector<Declaration> declarations;
  std::size_t dependency_count = 0;
  for (const auto& artifact : artifacts) {
    const auto digest = artifact.at("sha256").get<std::string>();
    const auto& facts = artifact.at("facts");
    if (digest.size() != 64 || facts.at("artifact_sha256") != digest)
      throw std::invalid_argument("facts_identity_mismatch");
    if (facts.value("status", "") != "complete_declared")
      issues.push_back(issue("incomplete_metadata", digest, {}, {}, nullptr, "warning"));
    const auto& mods = facts.at("mods");
    if (!mods.is_array() || mods.size() > 8192) throw std::invalid_argument("mod_budget");
    const bool has_neo = std::any_of(mods.begin(), mods.end(), [](const Json& m) {
      return m.value("loader", "") == "neoforge";
    });
    bool active = false;
    std::size_t mod_index = 0;
    for (const auto& mod : mods) {
      const auto identity = artifact.value("path", digest) + "/" + std::to_string(mod_index++);
      if ((loader == "neoforge" || loader == "forge") && mod.contains("container_type") &&
          !mod["container_type"].is_null() && mod["container_type"] != "MOD")
        continue;
      if (!active_format(mod.value("loader", ""), loader, has_neo) ||
          !client_side(mod.value("environment", Json())))
        continue;
      active = true;
      const auto id = mod.at("mod_id").get<std::string>();
      const auto version = mod.value("version_resolved", Json());
      const auto resolved = version.is_string() ? version.get<std::string>() : std::string{};
      providers[id].push_back({digest, resolved, identity});
      for (const auto& alias : mod.value("provides", Json::array()))
        if (alias.is_string() && alias != id)
          providers[alias.get<std::string>()].push_back({digest, resolved, identity});
      declarations.push_back({digest, mod});
      dependency_count += mod.value("dependencies", Json::array()).size();
      if (dependency_count > 65536) throw std::invalid_argument("dependency_budget");
    }
    if (!active)
      issues.push_back(issue("no_active_loader_metadata", digest, {}, {}, nullptr, "warning"));
  }
  for (const auto& [id, values] : providers) {
    std::set<std::string> owners;
    for (const auto& value : values) owners.insert(value.identity);
    if (owners.size() > 1)
      issues.push_back(issue("duplicate_provider", values.front().artifact, id, id));
  }
  std::map<std::string, std::set<std::string>> ordering;
  for (const auto& declaration : declarations) {
    const auto& mod = declaration.mod;
    const auto id = mod.at("mod_id").get<std::string>();
    const auto dialect = mod.value("loader", "") == "fabric" ? "fabric" : "maven";
    for (const auto& dependency : mod.value("dependencies", Json::array())) {
      if (!client_side(dependency.value("environment", Json()))) continue;
      const auto target = dependency.at("target_id").get<std::string>();
      const auto relation = dependency.at("relation").get<std::string>();
      const auto range = dependency.value("version_raw", Json());
      const auto evidence = dependency.value("source_path", "");
      const auto found = providers.find(target);
      const bool required = relation == "required" || relation == "depends";
      const bool negative = relation == "incompatible" || relation == "breaks";
      const bool warning = relation == "discouraged" || relation == "conflicts" ||
                           relation == "recommends" || relation == "suggests";
      const auto severity = warning ? "warning" : "error";
      if (found == providers.end()) {
        if (required)
          issues.push_back(issue("missing_dependency", declaration.artifact, id, target, range,
                                 severity, evidence));
        continue;
      }
      for (const auto& provider : found->second) {
        const auto matched = matches(provider.version, range, dialect);
        if (!matched) {
          issues.push_back(issue("unknown_version_expression", declaration.artifact, id, target,
                                 range, "warning", evidence));
        } else if ((negative || relation == "discouraged" || relation == "conflicts") ? *matched
                                                                                      : !*matched) {
          auto problem = issue(negative ? "incompatible_dependency" : "version_constraint",
                               declaration.artifact, id, target, range, severity, evidence);
          problem["found"] = provider.version;
          problem["provider_artifact"] = provider.artifact;
          issues.push_back(problem);
        }
      }
      const auto order = dependency.value("ordering", Json());
      if (order == "AFTER") ordering[target].insert(id);
      if (order == "BEFORE") ordering[id].insert(target);
    }
  }
  // Required dependency cycles can be satisfied. Only explicit load-order
  // cycles are rejected; keeping these two graphs separate is essential.
  std::map<std::string, int> indegree;
  for (const auto& [from, targets] : ordering) {
    indegree.try_emplace(from, 0);
    for (const auto& target : targets) ++indegree[target];
  }
  std::vector<std::string> ready;
  for (const auto& [id, degree] : indegree)
    if (!degree) ready.push_back(id);
  std::size_t visited = 0;
  while (!ready.empty()) {
    auto id = ready.back();
    ready.pop_back();
    ++visited;
    for (const auto& target : ordering[id])
      if (!--indegree[target]) ready.push_back(target);
  }
  if (visited != indegree.size()) issues.push_back(issue("load_order_cycle", "environment"));
  static const auto built_in = Json::parse(kBuggRuntimeRules).at("rules");
  auto rules = built_in;
  for (const auto& rule : input.value("runtime_rules", Json::array())) rules.push_back(rule);
  if (rules.size() > 256) throw std::invalid_argument("runtime_rule_budget");
  for (const auto& rule : rules) {
    bool applies = true;
    for (auto item = rule.at("environment").begin(); item != rule.at("environment").end(); ++item)
      applies &= environment.contains(item.key()) && environment.at(item.key()) == item.value();
    if (!applies) continue;
    for (const auto& artifact : artifacts)
      if (artifact.at("sha256") == rule.at("sha256")) {
        auto problem = issue("known_runtime_failure", artifact.at("sha256"), {}, {}, nullptr,
                             "error", rule.value("reference", ""));
        problem["reason"] = rule.value("reason", "");
        issues.push_back(problem);
      }
  }
  const bool errors = std::any_of(issues.begin(), issues.end(),
                                  [](const Json& i) { return i.at("severity") == "error"; });
  return {{"schema", "bugg-dependency-check-v1"},
          {"state", errors           ? "conflict"
                    : issues.empty() ? "satisfied_declared"
                                     : "unverified"},
          {"issues", issues},
          {"runtime_verified", false}};
}
Json parse(std::string_view input) {
  if (input.size() > 8 * 1024 * 1024) throw std::invalid_argument("input_budget");
  return Json::parse(input);
}
}  // namespace
std::string check_json(std::string_view input) { return check(parse(input)).dump(); }
std::string solve_json(std::string_view raw) {
  auto input = parse(raw);
  const auto initial = input.at("artifacts");
  const auto candidates = input.value("candidates", Json::array());
  if (candidates.size() > 128 || initial.size() > 4096)
    throw std::invalid_argument("candidate_budget");
  std::set<std::string> seen;
  Json best;
  std::size_t steps = 0, best_cost = 129;
  std::function<void(const Json&, std::size_t)> search = [&](const Json& artifacts,
                                                             std::size_t depth) {
    if (++steps > 4096 || depth > 32) return;
    std::vector<std::string> ids;
    for (const auto& artifact : artifacts) ids.push_back(artifact.at("sha256"));
    std::sort(ids.begin(), ids.end());
    auto key = Json(ids).dump();
    if (!seen.insert(key).second) return;
    auto state = input;
    state["artifacts"] = artifacts;
    auto checked = check(state);
    if (checked.at("state") == "satisfied_declared") {
      std::size_t cost = 0;
      for (const auto& a : initial)
        if (std::find(ids.begin(), ids.end(), a.at("sha256").get<std::string>()) == ids.end())
          ++cost;
      for (const auto& a : artifacts)
        if (std::none_of(initial.begin(), initial.end(),
                         [&](const Json& old) { return old.at("sha256") == a.at("sha256"); }))
          ++cost;
      if (cost < best_cost) {
        best_cost = cost;
        best = artifacts;
      }
      return;
    }
    const auto& issues = checked.at("issues");
    auto failure = std::find_if(issues.begin(), issues.end(),
                                [](const Json& i) { return i.at("severity") == "error"; });
    if (failure == issues.end()) return;  // unknown metadata is not a solved plan
    for (const auto& candidate : candidates) {
      const auto digest = candidate.at("sha256").get<std::string>();
      if (std::find(ids.begin(), ids.end(), digest) != ids.end()) continue;
      const auto replace = candidate.value("replaces", "");
      bool relevant = !replace.empty() && (replace == failure->value("artifact", "") ||
                                           replace == failure->value("provider_artifact", ""));
      for (const auto& m : candidate.at("facts").at("mods"))
        relevant |= m.at("mod_id") == failure->value("target_id", "");
      if (!relevant) continue;
      Json next = Json::array();
      bool forbidden = false;
      for (const auto& a : artifacts) {
        if (!replace.empty() && a.at("sha256") == replace) {
          forbidden |= a.value("locked", false) && !input.value("allow_locked_changes", false);
        } else
          next.push_back(a);
      }
      if (forbidden) continue;
      next.push_back(candidate);
      search(next, depth + 1);
    }
  };
  search(initial, 0);
  return Json{
      {"schema", "bugg-dependency-solution-v1"},
      {"state", best.is_null() ? (steps > 4096 ? "budget_exhausted" : "no_verified_solution")
                               : "resolved_declared"},
      {"artifacts", best.is_null() ? initial : best},
      {"steps", steps},
      {"runtime_verified", false}}
      .dump();
}
}  // namespace bugg::dependency
