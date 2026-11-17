#include "modules/game_install/infrastructure/resource_source_provider.h"

#include <array>

#include "modules/game_install/infrastructure/bmclapi_resource_source.h"
#include "modules/game_install/infrastructure/bugg_resource_source.h"
#include "modules/game_install/infrastructure/official_resource_source.h"

namespace bugg {
const ResourceSourceProvider* resource_source_provider(const QString& id) {
  static const BuggResourceSource bugg;
  static const BmclapiResourceSource bmclapi;
  static const OfficialResourceSource official;
  static const std::array<const ResourceSourceProvider*, 3> providers{&bugg, &bmclapi, &official};
  for (const auto* provider : providers)
    if (provider->id() == id) return provider;
  return nullptr;
}
}  // namespace bugg
