#include <cstdlib>
#include <iostream>
#include <string_view>

#include "bugg/dependency_version.h"

int main() {
  using namespace bugg::dependency;
  const auto check = [](bool pass, std::string_view name) {
    if (!pass) {
      std::cerr << "FAIL " << name << '\n';
      std::exit(1);
    }
  };
  check(compare_maven("1", "1.0.0-final") == 0, "release aliases and zero normalization");
  check(compare_maven("1.0alpha1", "1.0-alpha-1") == 0, "alpha aliases and nested lists");
  check(compare_maven("1.0-RC2", "1.0-rc3") == -1, "case insensitive qualifiers");
  check(compare_maven("1.0.0.X1", "1.0.0-X2") == -1, "nested qualifier transition");
  check(compare_maven("1-sp", "1") == 1, "service pack after release");
  check(compare_maven("1-unknown", "1-sp") == 1, "unknown qualifier ordering");
  check(compare_maven("1.999999999999999999999", "1.1000000000000000000000") == -1,
        "arbitrary precision decimal components");
  check(matches_maven("1.11.7+mc26.3", "(,1.12.1)") == true, "actual sodium exclusion");
  check(matches_maven("26.3.0.101", "[26.1.2.10-beta,)") == true, "actual loader requirement");
  check(matches_maven("2", "[1,2)") == false, "exclusive upper boundary");
  check(matches_maven("1", "[1,2)") == true, "inclusive lower boundary");
  check(matches_maven("1.1", "(,1],[1.2,)") == false, "union gap");
  check(matches_maven("1.2", "(,1],[1.2,)") == true, "union includes second interval");
  check(matches_maven("1.0", "[1]") == true, "exact Maven equality");
  check(!matches_maven("1", "[2,1)").has_value(), "invalid inverted range is unknown");
  check(!matches_maven("1", "[1,2),").has_value(), "malformed union not silently accepted");
  check(!matches_maven("${version}", "*").has_value(), "unresolved placeholder is unknown");
  check(!matches_maven("1", ">=1").has_value(), "different dialect not guessed");
  check(matches_maven("9", "1.0") == true, "bare Maven recommendation is not an exact constraint");
  check(matches_fabric("0.8.4", "^0.2") == true, "Fabric caret retains the complete major component");
  check(matches_fabric("1.21.3", ">=1.21 <1.22") == true, "Fabric predicates are AND");
  check(matches_fabric("26.3", "1.21.x") == false, "new game naming does not match old major");
  check(matches_fabric("1.2.7-beta.1", "1.2.x") == true, "Fabric wildcard includes prerelease");
  check(matches_fabric("1.3.0-beta.1", "1.2.x") == false, "Fabric wildcard cannot leak next minor");
  check(matches_fabric("build-label", ">=build-label") == true, "non-semantic inclusive reference is equality");
  check(!matches_fabric("1.2.0", ">=1.x").has_value(), "invalid wildcard range remains unknown");
  std::cout << "PASS Maven normalization, boundaries, unions, actual "
               "Iris/Sodium constraints\n";
}
