#include <cstdlib>
#include <iostream>

#include "bugg/dependency_check.h"
#include "json.hpp"

using Json = nlohmann::json;
void require(bool pass, const char* label) {
  if (!pass) {
    std::cerr << label << '\n';
    std::exit(1);
  }
}
Json artifact(char hash, const char* name, const char* version, Json dependencies = Json::array()) {
  const std::string digest(64, hash);
  return {{"sha256", digest},
          {"facts",
           {{"artifact_sha256", digest},
            {"status", "complete_declared"},
            {"mods", Json::array({{{"mod_id", name},
                                   {"version_resolved", version},
                                   {"loader", "neoforge"},
                                   {"dependencies", dependencies}}})}}}};
}
Json dependency(const char* target, const char* range, const char* relation = "required") {
  return {{"target_id", target}, {"relation", relation}, {"version_raw", range}};
}
Json check(Json value) { return Json::parse(bugg::dependency::check_json(value.dump())); }
int main() {
  Json input{{"environment",
              {{"minecraft", "26.3"}, {"loader", "neoforge"}, {"loader_version", "26.3.0.101"}}}};
  auto java_input = input;
  java_input["artifacts"] =
      Json::array({artifact('j', "java_mod", "1", Json::array({dependency("java", "[21,25)")}))});
  java_input["minimum_java"] = 17;
  java_input["candidates"] = Json::array({25, 21, 17});
  require(Json::parse(bugg::dependency::select_java_json(java_input.dump()))["major"] == 21,
          "Java upper bound rejects a newer JVM and selects the common version");
  java_input["minimum_java"] = 25;
  require(Json::parse(bugg::dependency::select_java_json(java_input.dump()))["major"].is_null(),
          "class bytecode minimum and declaration upper bound can be unsatisfiable");
  auto a = artifact('a', "alpha", "1", Json::array({dependency("library", "[1,3)")}));
  auto b = artifact('b', "beta", "1", Json::array({dependency("library", "[2,4)")}));
  auto library1 = artifact('c', "library", "1");
  auto library2 = artifact('d', "library", "2");
  input["artifacts"] = Json::array({a});
  require(check(input)["state"] == "conflict", "ordinary missing dependency stays an error");
  auto locator = artifact('e', "locator", "1");
  locator["facts"]["evidence"] = Json::array(
      {{{"container_path", "root"},
        {"member_path",
         "META-INF/services/net.neoforged.neoforgespi.locating.IModFileCandidateLocator"},
        {"size", 24}}});
  input["artifacts"].push_back(locator);
  require(check(input)["state"] == "unverified",
          "custom locator leaves missing runtime identity unverified");
  input["artifacts"].push_back(library2);
  require(check(input)["state"] == "satisfied_declared", "declared dependencies remain verifiable");
  input["artifacts"] = Json::array({a, b, library1});
  require(check(input)["state"] == "conflict", "multiple-parent intersection rejected");
  library2["replaces"] = library1["sha256"];
  input["candidates"] = Json::array({library2});
  auto solution = Json::parse(bugg::dependency::solve_json(input.dump()));
  require(solution["state"] == "resolved_declared", "global combination solved");
  input["artifacts"][2]["locked"] = true;
  require(
      Json::parse(bugg::dependency::solve_json(input.dump()))["state"] == "no_verified_solution",
      "author pin preserved");
  input["allow_locked_changes"] = true;
  require(Json::parse(bugg::dependency::solve_json(input.dump()))["state"] == "resolved_declared",
          "explicit repair unlocks pack");
  input["artifacts"] = Json::array(
      {artifact('a', "alpha", "1", Json::array({dependency("library", "[2,3)", "optional")}))});
  require(check(input)["state"] == "satisfied_declared", "optional absent does not install");
  input["artifacts"].push_back(library1);
  require(check(input)["state"] == "conflict", "optional present must satisfy range");
  input["artifacts"] = Json::array(
      {artifact('a', "alpha", "1", Json::array({dependency("library", "[1,)", "incompatible")})),
       library1});
  require(check(input)["state"] == "conflict", "declared incompatible version rejected");
  auto duplicate = library1;
  duplicate["path"] = "mods/other-name.jar";
  library1["path"] = "mods/library.jar";
  input["artifacts"] = Json::array({library1, duplicate});
  require(check(input)["state"] == "conflict",
          "identical bytes in two active paths still duplicate");
  auto nested = library1;
  nested["facts"]["mods"][0]["loader"] = "fabric";
  nested["facts"]["mods"][0]["container_path"] = "root!/libs/base.jar";
  nested["facts"]["evidence"] = Json::array({{{"container_path", "root"},
                                              {"member_path", "libs/base.jar"},
                                              {"sha256", std::string(64, 'e')}}});
  auto second_parent = nested;
  second_parent["sha256"] = std::string(64, 'f');
  second_parent["facts"]["artifact_sha256"] = second_parent["sha256"];
  Json fabric{{"environment", {{"loader", "fabric"}, {"loader_version", "0.16.14"}}},
              {"artifacts", Json::array({nested, second_parent})}};
  require(check(fabric)["state"] == "satisfied_declared",
          "byte-identical Fabric nested libraries share one provider");
  fabric["artifacts"][1]["facts"]["evidence"][0]["sha256"] = std::string(64, 'a');
  require(check(fabric)["state"] == "satisfied_declared",
          "Fabric selects one optional nested provider rather than loading both");
  auto fabric_root = library1;
  fabric_root["facts"]["mods"][0]["loader"] = "fabric";
  fabric["artifacts"].push_back(fabric_root);
  require(check(fabric)["state"] == "satisfied_declared",
          "Fabric root provider replaces optional nested copy");
  auto fabric_duplicate = fabric_root;
  fabric_duplicate["path"] = "mods/duplicate.jar";
  fabric["artifacts"].push_back(fabric_duplicate);
  require(check(fabric)["state"] == "conflict", "Fabric duplicate root mods remain an error");
  auto forge_nested = nested;
  forge_nested["facts"]["mods"][0]["loader"] = "neoforge";
  auto other_nested = forge_nested;
  other_nested["sha256"] = std::string(64, 'f');
  other_nested["facts"]["artifact_sha256"] = std::string(64, 'f');
  const Json coordinate{{"container_path", "root"}, {"path", "libs/base.jar"}, {"group", "example"},
                        {"artifact", "base"},       {"version", "1"},          {"range", "[1,)"}};
  forge_nested["facts"]["nested_artifacts"] = Json::array({coordinate});
  other_nested["facts"]["nested_artifacts"] = Json::array({coordinate});
  auto jarjar = input;
  jarjar["artifacts"] = Json::array({forge_nested, other_nested});
  require(check(jarjar)["state"] == "satisfied_declared",
          "Forge selects one shared JarJar coordinate");
  jarjar["artifacts"][1]["facts"]["nested_artifacts"][0]["range"] = "[2,3)";
  require(check(jarjar)["state"] == "conflict",
          "incompatible JarJar parent ranges remain conflicts");
  jarjar["artifacts"].push_back(library1);
  require(check(jarjar)["state"] == "satisfied_declared",
          "root mod replaces JarJar copies with the same loader identifier");
  auto undiscovered = forge_nested;
  undiscovered["facts"].erase("nested_artifacts");
  jarjar["artifacts"] = Json::array({undiscovered, library1});
  require(check(jarjar)["state"] != "conflict",
          "Forge ignores a nested mod not declared by JarJar");
  auto quilt_mod = artifact('a', "alpha", "1", Json::array({dependency("fabricloader", ">=0.16")}));
  quilt_mod["facts"]["mods"][0]["loader"] = "fabric";
  Json quilt{{"environment", {{"loader", "quilt"}, {"loader_version", "0.29.3"}}},
             {"artifacts", Json::array({quilt_mod})}};
  require(check(quilt)["state"] == "conflict", "Quilt version is not Fabric compatibility version");
  quilt["environment"]["fabric_loader_version"] = "0.16.0";
  require(check(quilt)["state"] == "satisfied_declared",
          "actual Quilt Fabric alias satisfies mods");
  quilt["environment"]["fabric_loader_version"] = "0.15.0";
  require(check(quilt)["state"] == "conflict", "Quilt alias still enforces Fabric version ranges");
  auto legacy_mod = artifact('a', "alpha", "1", Json::array({dependency("forge", "[47,48)")}));
  legacy_mod["facts"]["mods"][0]["loader"] = "forge_toml";
  Json legacy{
      {"environment",
       {{"loader", "neoforge"}, {"minecraft", "1.20.1"}, {"loader_version", "1.20.1-47.1.106"}}},
      {"artifacts", Json::array({legacy_mod})}};
  require(check(legacy)["state"] == "satisfied_declared",
          "legacy NeoForge provides exact Forge version");
  legacy["environment"]["minecraft"] = "1.20.2";
  require(check(legacy)["state"] == "conflict",
          "legacy Forge alias does not extend to later Minecraft");
  auto wrapper = library1;
  wrapper["facts"]["mods"][0]["container_type"] = "LIBRARY";
  wrapper["facts"]["mods"].push_back(library1["facts"]["mods"][0]);
  input["artifacts"] = Json::array({wrapper});
  require(check(input)["state"] == "satisfied_declared",
          "library wrapper is not an active duplicate mod");
  auto parsed = Json::parse(
      bugg::dependency::metadata_json(Json{{"members", {{"META-INF/neoforge.mods.toml", R"TOML(
modLoader="javafml"
loaderVersion="[1,)"
[[mods]]
modId="alpha"
displayName="Actual Name"
version="2"
[[dependencies.alpha]]
modId="library"
versionRange="[2,3)"
side="CLIENT"
[[dependencies.template]]
modId="minecraft"
type="required"
versionRange="[1,)"
)TOML"}}}}.dump()));
  require(parsed["mods"][0]["dependencies"][0]["version_raw"] == "[2,3)",
          "TOML structure retains exact version range");
  require(parsed["mods"][0]["declared_name"] == "Actual Name", "package name retained");
  require(parsed["mods"][0]["dependencies"][0]["relation"] == "required",
          "NeoForge missing type follows official required default");
  require(parsed["issues"][0]["code"] == "orphan_dependency_owner" &&
              parsed["issues"][0]["detail"] == "template",
          "orphan owner is not reassigned");
  for (const auto* path : {"META-INF/neoforge.mods.toml", "META-INF/mods.toml"}) {
    const auto java_metadata = Json::parse(bugg::dependency::metadata_json(Json{
        {"members",
         {{path,
           "[[mods]]\nmodId='alpha'\nversion='1'\n"
           "[features.alpha]\njavaVersion='[21,25)'\n"}}}}.dump()));
    const auto& java_rule = java_metadata["mods"][0]["dependencies"][0];
    require(java_rule["target_id"] == "java" && java_rule["version_raw"] == "[21,25)",
            "Forge and NeoForge Java features retain both range bounds");
    for (const auto& [declared, normalized] : {std::pair{"REQUIRED", "required"},
                                               {"Optional", "optional"},
                                               {"InCompatible", "incompatible"},
                                               {"DISCOURAGED", "discouraged"}}) {
      auto text = std::string("[[mods]]\nmodId='alpha'\nversion='1'\n[[dependencies.alpha]]\n") +
                  "modId='minecraft'\ntype='" + declared + "'\nversionRange='[1,)'\n";
      const auto result =
          Json::parse(bugg::dependency::metadata_json(Json{{"members", {{path, text}}}}.dump()));
      const auto& row = result["mods"][0]["dependencies"][0];
      require(row["relation"] == normalized, "NeoForge dependency type is case insensitive");
      require(row["raw"]["type"] == declared, "Original dependency spelling remains evidence");
    }
  }
  bool rejected = false;
  try {
    bugg::dependency::metadata_json(Json{
        {"members",
         {{"META-INF/neoforge.mods.toml",
           "[[mods]]\nmodId='alpha'\n[[dependencies.alpha]]\nmodId='minecraft'\ntype='unknown'"}}}}
                                        .dump());
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  require(rejected, "Unknown dependency types still fail");
  std::cout << "PASS global intersection, locks, optional/conflicts, native TOML\n";
}
