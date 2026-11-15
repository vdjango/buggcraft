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
  bool root = true;
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
  if (loader == "fabric" || loader == "quilt") return format == "fabric";
  return false;
}
Json check(const Json& input) {
  const auto& environment = input.at("environment");
  const auto loader = environment.at("loader").get<std::string>();
  const auto& artifacts = input.at("artifacts");
  if (!artifacts.is_array() || artifacts.size() > 4096)
    throw std::invalid_argument("artifact_budget");
  Json issues = Json::array();
  Json runtime_locators = Json::array();
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
  if (loader == "neoforge" && environment.value("minecraft", "") == "1.20.1") {
    auto version = environment.value("loader_version", "");
    if (version.starts_with("1.20.1-")) version.erase(0, 7);
    if (version.starts_with("47.")) builtin("forge", version);
  }
  if (loader == "quilt") builtin("fabricloader", environment.value("fabric_loader_version", ""));
  struct Declaration {
    std::string artifact, identity;
    Json mod;
  };
  std::vector<Declaration> declarations;
  std::size_t dependency_count = 0;
  // Forge JarJar selects one library coordinate satisfying all parent ranges.
  // Different packaging bytes of that selected library are not duplicate root mods.
  std::set<std::string> ignored_containers;
  std::set<std::string> root_identifiers;
  const auto container_identifier = [&](const Json& facts, const std::string& container) {
    std::set<std::string> ids;
    const auto& mods = facts.at("mods");
    const bool has_neo = std::any_of(mods.begin(), mods.end(), [](const Json& m) {
      return m.value("loader", "") == "neoforge";
    });
    for (const auto& mod : mods)
      if (mod.value("container_path", "root") == container &&
          active_format(mod.value("loader", ""), loader, has_neo))
        ids.insert(mod.at("mod_id").get<std::string>());
    std::string result;
    for (const auto& id : ids) result += id;
    return result;
  };
  for (const auto& artifact : artifacts) {
    const auto id = container_identifier(artifact.at("facts"), "root");
    if (!id.empty()) root_identifiers.insert(id);
  }
  if (loader == "neoforge" || loader == "forge") {
    std::map<std::string, std::vector<Json>> libraries;
    for (const auto& artifact : artifacts) {
      const auto digest = artifact.at("sha256").get<std::string>();
      const auto nested = artifact.at("facts").value("nested_artifacts", Json::array());
      std::set<std::string> reachable{"root"};
      bool expanded = true;
      while (expanded) {
        expanded = false;
        for (const auto& library : nested) {
          const auto parent = library.at("container_path").get<std::string>();
          const auto child = parent + "!/" + library.at("path").get<std::string>();
          if (reachable.contains(parent) &&
              !root_identifiers.contains(container_identifier(artifact.at("facts"), child)))
            expanded |= reachable.insert(child).second;
        }
      }
      for (auto library : nested) {
        if (!reachable.contains(library.at("container_path").get<std::string>())) continue;
        library["owner"] = digest + "/" + library.at("container_path").get<std::string>() + "!/" +
                           library.at("path").get<std::string>();
        library["mod_identifier"] = container_identifier(
            artifact.at("facts"), library.at("container_path").get<std::string>() + "!/" +
                                      library.at("path").get<std::string>());
        libraries[library.at("group").get<std::string>() + ":" +
                  library.at("artifact").get<std::string>()]
            .push_back(library);
      }
    }
    std::map<std::string, std::string> selected_identifiers;
    for (const auto& [coordinate, copies] : libraries) {
      // JarSelector's already loaded mod identifier takes precedence over an
      // embedded copy, even when its Maven coordinate or bytes differ.
      if (std::any_of(copies.begin(), copies.end(), [&](const Json& copy) {
            return root_identifiers.contains(copy.at("mod_identifier").get<std::string>());
          })) {
        for (const auto& copy : copies)
          ignored_containers.insert(copy.at("owner").get<std::string>());
        continue;
      }
      const Json* selected = nullptr;
      const auto selector = environment.value("jarjar_version", "");
      std::set<std::string> distinct_metadata;
      for (const auto& copy : copies)
        distinct_metadata.insert(copy.at("path").dump() + copy.at("version").dump() +
                                 copy.at("range").dump());
      // JarJar 0.3.x quick-returns a sole ContainedJarMetadata before testing
      // its own range. Newer selectors validate it; use the actual library version.
      if (!selector.empty() && compare_maven(selector, "0.4").value_or(0) < 0 &&
          distinct_metadata.size() == 1)
        selected = &copies.front();
      for (const auto& candidate : copies) {
        if (selected && distinct_metadata.size() == 1) break;
        const auto version = candidate.at("version").get<std::string>();
        const bool accepted = std::all_of(copies.begin(), copies.end(), [&](const Json& parent) {
          return matches_maven(version, parent.at("range").get<std::string>()).value_or(false);
        });
        if (accepted &&
            (!selected ||
             compare_maven(version, selected->at("version").get<std::string>()).value_or(0) > 0))
          selected = &candidate;
      }
      if (!selected) {
        issues.push_back(issue("nested_library_conflict", "", coordinate, coordinate));
        continue;
      }
      const auto identifier = selected->at("mod_identifier").get<std::string>();
      if (!identifier.empty()) {
        const auto [found, inserted] =
            selected_identifiers.emplace(identifier, selected->at("owner").get<std::string>());
        if (!inserted && found->second != selected->at("owner").get<std::string>())
          ignored_containers.insert(selected->at("owner").get<std::string>());
      }
      for (const auto& copy : copies)
        if (copy.at("owner") != selected->at("owner"))
          ignored_containers.insert(copy.at("owner").get<std::string>());
    }
  }
  for (const auto& artifact : artifacts) {
    const auto digest = artifact.at("sha256").get<std::string>();
    const auto& facts = artifact.at("facts");
    if (digest.size() != 64 || facts.at("artifact_sha256") != digest)
      throw std::invalid_argument("facts_identity_mismatch");
    // Custom locators can register runtime mod identities absent from mods.toml.
    // Their presence is evidence of uncertainty, never proof that a dependency exists.
    const auto service =
        loader == "forge" ? "META-INF/services/net.minecraftforge.forgespi.locating.IModLocator"
        : loader == "neoforge"
            ? "META-INF/services/net.neoforged.neoforgespi.locating.IModFileCandidateLocator"
            : "";
    for (const auto& evidence : facts.value("evidence", Json::array()))
      if (service[0] && evidence.value("container_path", "") == "root" &&
          evidence.value("member_path", "") == service && evidence.value("size", 0) > 0)
        runtime_locators.push_back({{"artifact", digest}, {"evidence", service}});
    if (facts.value("status", "") != "complete_declared")
      issues.push_back(issue("incomplete_metadata", digest, {}, {}, nullptr, "warning"));
    const auto& mods = facts.at("mods");
    if (!mods.is_array() || mods.size() > 8192) throw std::invalid_argument("mod_budget");
    const bool has_neo = std::any_of(mods.begin(), mods.end(), [](const Json& m) {
      return m.value("loader", "") == "neoforge";
    });
    std::set<std::string> discovered{"root"};
    if (loader == "neoforge" || loader == "forge") {
      bool changed = true;
      const auto nested = facts.value("nested_artifacts", Json::array());
      while (changed) {
        changed = false;
        for (const auto& library : nested) {
          const auto parent = library.at("container_path").get<std::string>();
          if (discovered.contains(parent))
            changed |=
                discovered.insert(parent + "!/" + library.at("path").get<std::string>()).second;
        }
      }
    }
    bool active = false;
    bool has_unignored_container = mods.empty();
    std::size_t mod_index = 0;
    std::map<std::string, std::string> containers;
    for (const auto& evidence : facts.value("evidence", Json::array())) {
      const auto hash = evidence.value("sha256", "");
      if (hash.size() == 64)
        containers[evidence.value("container_path", "") + "!/" +
                   evidence.value("member_path", "")] = hash;
    }
    std::map<std::string, std::size_t> container_indices;
    for (const auto& mod : mods) {
      auto identity = artifact.value("path", digest) + "/" + std::to_string(mod_index++);
      const auto container = mod.value("container_path", "root");
      // Parsing records all declarations; each loader only discovers its own
      // declared nested paths. Fabric's jars list is not Forge's JarJar list.
      if ((loader == "neoforge" || loader == "forge") && !discovered.contains(container)) continue;
      const auto container_identity = digest + "/" + container;
      if (std::any_of(ignored_containers.begin(), ignored_containers.end(),
                      [&](const auto& ignored) {
                        return container_identity == ignored ||
                               container_identity.starts_with(ignored + "!/");
                      }))
        continue;
      has_unignored_container = true;
      const auto local_index = container_indices[container]++;
      // Fabric discovers byte-identical nested libraries once across parents.
      // Root files and different nested bytes retain their separate identities.
      if ((loader == "fabric" || loader == "quilt") && container != "root" &&
          containers.count(container))
        identity = "nested/" + containers.at(container) + "/" + std::to_string(local_index);
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
      providers[id].push_back({digest, resolved, identity, container == "root"});
      for (const auto& alias : mod.value("provides", Json::array()))
        if (alias.is_string() && alias != id)
          providers[alias.get<std::string>()].push_back(
              {digest, resolved, identity, container == "root"});
      declarations.push_back({digest, identity, mod});
      dependency_count += mod.value("dependencies", Json::array()).size();
      if (dependency_count > 65536) throw std::invalid_argument("dependency_budget");
    }
    if (!active && has_unignored_container)
      issues.push_back(issue("no_active_loader_metadata", digest, {}, {}, nullptr, "warning"));
  }
  if (loader == "fabric" || loader == "quilt") {
    std::set<std::string> unselected;
    for (auto& [id, values] : providers) {
      if (values.size() < 2) continue;
      const bool has_root =
          std::any_of(values.begin(), values.end(), [](const Provider& p) { return p.root; });
      const Provider* selected = nullptr;
      if (!has_root) {
        for (const auto& candidate : values) {
          bool accepted = true;
          for (const auto& declaration : declarations)
            for (const auto& dependency : declaration.mod.value("dependencies", Json::array())) {
              const auto relation = dependency.at("relation").get<std::string>();
              if (dependency.at("target_id") != id ||
                  (relation != "required" && relation != "depends") ||
                  !client_side(dependency.value("environment", Json())))
                continue;
              const auto matched =
                  matches(candidate.version, dependency.value("version_raw", Json()), "fabric");
              if (matched && !*matched) accepted = false;
            }
          if (accepted &&
              (!selected || compare_maven(candidate.version, selected->version).value_or(0) > 0))
            selected = &candidate;
        }
      }
      for (const auto& value : values)
        if (!value.root && (has_root || (selected && value.identity != selected->identity)))
          unselected.insert(value.identity);
    }
    for (auto& [id, values] : providers)
      std::erase_if(values, [&](const Provider& p) { return unselected.contains(p.identity); });
    std::erase_if(declarations,
                  [&](const Declaration& d) { return unselected.contains(d.identity); });
  }
  for (const auto& [id, values] : providers) {
    std::set<std::string> owners;
    for (const auto& value : values) owners.insert(value.identity);
    if (owners.size() > 1) {
      auto problem = issue("duplicate_provider", values.front().artifact, id, id);
      problem["providers"] = Json::array();
      for (const auto& value : values)
        problem["providers"].push_back({{"artifact", value.artifact},
                                        {"version", value.version},
                                        {"identity", value.identity},
                                        {"root", value.root}});
      issues.push_back(problem);
    }
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
        if (required) {
          auto problem = issue(
              runtime_locators.empty() ? "missing_dependency" : "unverified_runtime_dependency",
              declaration.artifact, id, target, range,
              runtime_locators.empty() ? severity : "warning", evidence);
          if (!runtime_locators.empty()) problem["runtime_locators"] = runtime_locators;
          issues.push_back(problem);
        }
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
std::string select_java_json(std::string_view raw) {
  auto input = Json::parse(raw);
  const auto minimum = input.value("minimum_java", 8);
  const auto candidates = input.at("candidates");
  if (!candidates.is_array() || candidates.size() > 64 || minimum < 1 || minimum > 99)
    throw std::invalid_argument("java_candidate_budget");
  Json last = Json::array();
  for (const auto& value : candidates) {
    if (!value.is_number_integer()) throw std::invalid_argument("invalid_java_candidate");
    const auto major = value.get<int>();
    if (major < minimum || major > 99) continue;
    input["environment"]["java"] = std::to_string(major);
    const auto checked = Json::parse(check_json(input.dump()));
    last = Json::array();
    for (const auto& problem : checked.at("issues"))
      if (problem.value("target_id", "") == "java") last.push_back(problem);
    if (last.empty()) return Json{{"major", major}, {"issues", last}}.dump();
  }
  return Json{{"major", nullptr}, {"issues", last}, {"state", "no_compatible_java"}}.dump();
}
}  // namespace bugg::dependency
