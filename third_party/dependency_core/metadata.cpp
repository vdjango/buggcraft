#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <vector>

#include "bugg/dependency_check.h"
#include "json.hpp"
#include "toml.hpp"

namespace bugg::dependency {
namespace {
using Json = nlohmann::json;
Json strict_json(const std::string& bytes) {
  std::vector<std::set<std::string>> keys;
  return Json::parse(bytes, [&](int, Json::parse_event_t event, Json& value) {
    if (event == Json::parse_event_t::object_start) keys.emplace_back();
    if (event == Json::parse_event_t::key && !keys.back().insert(value.get<std::string>()).second)
      throw std::invalid_argument("duplicate_json_key");
    if (event == Json::parse_event_t::object_end) keys.pop_back();
    return true;
  });
}
std::string id(const Json& value) {
  if (!value.is_string()) throw std::invalid_argument("missing_mod_id");
  auto result = value.get<std::string>();
  if (result.empty() || result.size() > 256) throw std::invalid_argument("invalid_mod_id");
  return result;
}
Json dependency(std::string target, std::string relation, Json range, Json side, Json ordering,
                std::string path, Json raw) {
  return {{"target_id", target}, {"relation", relation}, {"version_raw", range},
          {"environment", side}, {"ordering", ordering}, {"source_path", path},
          {"raw", raw}};
}
std::map<std::string, std::string> manifest_attributes(const std::string& text) {
  std::istringstream input(text);
  std::string line, key, value;
  std::map<std::string, std::string> fields;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty()) break;
    if (line.starts_with(' ')) {
      if (!key.empty()) fields[key] += line.substr(1);
      continue;
    }
    const auto colon = line.find(": ");
    if (colon == line.npos) continue;
    key = line.substr(0, colon);
    std::transform(key.begin(), key.end(), key.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    if (fields.contains(key)) throw std::invalid_argument("duplicate_manifest_attribute");
    fields[key] = line.substr(colon + 2);
  }
  return fields;
}
}  // namespace
std::string metadata_json(std::string_view raw) {
  if (raw.size() > 8 * 1024 * 1024) throw std::invalid_argument("metadata_budget");
  const auto input = strict_json(std::string(raw));
  Json mods = Json::array(), issues = Json::array(), nested = Json::array();
  const auto& members = input.at("members");
  const auto container = input.value("container_path", "root");
  const auto attributes = manifest_attributes(members.value("META-INF/MANIFEST.MF", ""));
  const auto found_version = attributes.find("implementation-version");
  const auto manifest =
      found_version == attributes.end() ? std::optional<std::string>{} : found_version->second;
  for (auto entry = members.begin(); entry != members.end(); ++entry) {
    const auto path = entry.key();
    if (!entry->is_string() || entry->get_ref<const std::string&>().size() > 1024 * 1024)
      throw std::invalid_argument("metadata_member_budget");
    if (path == "fabric.mod.json") {
      const auto document = strict_json(entry->get<std::string>());
      const auto identifier = id(document.at("id"));
      const auto version = id(document.at("version"));
      Json dependencies = Json::array();
      for (const auto relation : {"depends", "recommends", "suggests", "breaks", "conflicts"}) {
        const auto rows = document.value(relation, Json::object());
        if (!rows.is_object()) throw std::invalid_argument("invalid_fabric_dependency");
        for (auto row = rows.begin(); row != rows.end(); ++row) {
          if (!row->is_string() && !row->is_array())
            throw std::invalid_argument("invalid_fabric_predicate");
          dependencies.push_back(dependency(id(row.key()), relation, *row, nullptr, nullptr,
                                            path + "#/" + relation + "/" + row.key(), *row));
        }
      }
      const auto provides = document.value("provides", Json::array());
      if (!provides.is_array()) throw std::invalid_argument("invalid_fabric_provides");
      for (const auto& alias : provides) id(alias);
      const bool unresolved = version.find("${") != version.npos;
      mods.push_back({{"mod_id", identifier},
                      {"declared_name", document.value("name", Json())},
                      {"version_raw", version},
                      {"version_resolved", unresolved ? Json() : Json(version)},
                      {"loader", "fabric"},
                      {"container_path", container},
                      {"metadata_path", path},
                      {"environment", document.value("environment", Json())},
                      {"provides", provides},
                      {"loader_constraints", Json::object()},
                      {"dependencies", dependencies},
                      {"raw", document}});
      if (unresolved)
        issues.push_back(
            {{"code", "unresolved_version_placeholder"}, {"path", path}, {"detail", identifier}});
      for (const auto& jar : document.value("jars", Json::array()))
        nested.push_back(id(jar.at("file")));
    } else if (path == "META-INF/mods.toml" || path == "META-INF/neoforge.mods.toml") {
      auto table = toml::parse(entry->get<std::string>());
      std::ostringstream converted;
      converted << toml::json_formatter(table);
      const auto document = strict_json(converted.str());
      if (!document.contains("mods") || !document.at("mods").is_array())
        throw std::invalid_argument("invalid_mods_toml");
      std::set<std::string> identifiers;
      std::size_t ordinal = 0;
      for (const auto& mod : document.at("mods")) {
        const auto identifier = id(mod.at("modId"));
        if (!identifiers.insert(identifier).second) throw std::invalid_argument("duplicate_mod_id");
        Json dependencies = Json::array();
        const auto rows =
            document.value("dependencies", Json::object()).value(identifier, Json::array());
        std::size_t index = 0;
        for (const auto& row : rows) {
          const auto relation =
              row.contains("type") ? id(row.at("type"))
              : row.contains("mandatory") && row.at("mandatory").is_boolean()
                  ? row.at("mandatory").get<bool>() ? "required" : "optional"
                  : throw std::invalid_argument("missing_dependency_requirement_type");
          if (relation != "required" && relation != "optional" && relation != "incompatible" &&
              relation != "discouraged")
            throw std::invalid_argument("unknown_neoforge_dependency_type");
          dependencies.push_back(dependency(
              id(row.at("modId")), relation, row.value("versionRange", Json()),
              row.value("side", Json()), row.value("ordering", Json()),
              path + "#/dependencies/" + identifier + "/" + std::to_string(index++), row));
        }
        const auto version = mod.value("version", Json());
        auto resolved = version;
        if (version == "${file.jarVersion}")
          resolved = manifest ? Json(*manifest) : Json();
        else if (version.is_string() &&
                 version.get_ref<const std::string&>().find("${") != std::string::npos)
          resolved = nullptr;
        if (!version.is_null() && resolved.is_null())
          issues.push_back(
              {{"code", "unresolved_version_placeholder"}, {"path", path}, {"detail", identifier}});
        Json loader = Json::object();
        for (const auto key : {"modLoader", "loaderVersion"})
          if (document.contains(key)) loader[key] = document.at(key);
        mods.push_back(
            {{"mod_id", identifier},
             {"declared_name", mod.value("displayName", Json())},
             {"version_raw", version},
             {"version_resolved", resolved},
             {"loader", path.ends_with("neoforge.mods.toml") ? "neoforge" : "forge_toml"},
             {"container_path", container},
             {"metadata_path", path + "#/mods/" + std::to_string(ordinal++)},
             {"environment", nullptr},
             {"provides", Json::array()},
             {"loader_constraints", loader},
             {"dependencies", dependencies},
             {"raw", mod}});
      }
    } else if (path == "META-INF/jarjar/metadata.json") {
      const auto document = strict_json(entry->get<std::string>());
      for (const auto& jar : document.value("jars", Json::array()))
        nested.push_back(id(jar.at("path")));
    } else if (path == "quilt.mod.json" || path == "mcmod.info") {
      issues.push_back({{"code", "unsupported_metadata_format"}, {"path", path}, {"detail", ""}});
    }
  }
  for (auto& mod : mods)
    mod["container_type"] =
        attributes.contains("fmlmodtype") ? Json(attributes.at("fmlmodtype")) : Json();
  return Json{{"mods", mods},
              {"issues", issues},
              {"nested", nested},
              {"status", mods.empty() ? "unsupported" : "complete_declared"}}
      .dump();
}
}  // namespace bugg::dependency
