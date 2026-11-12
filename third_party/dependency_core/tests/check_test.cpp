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
  auto a = artifact('a', "alpha", "1", Json::array({dependency("library", "[1,3)")}));
  auto b = artifact('b', "beta", "1", Json::array({dependency("library", "[2,4)")}));
  auto library1 = artifact('c', "library", "1");
  auto library2 = artifact('d', "library", "2");
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
type="required"
versionRange="[2,3)"
side="CLIENT"
)TOML"}}}}.dump()));
  require(parsed["mods"][0]["dependencies"][0]["version_raw"] == "[2,3)",
          "TOML structure retains exact version range");
  require(parsed["mods"][0]["declared_name"] == "Actual Name", "package name retained");
  std::cout << "PASS global intersection, locks, optional/conflicts, native TOML\n";
}
