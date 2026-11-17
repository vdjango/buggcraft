#include "modules/game_install/infrastructure/official_resource_source.h"

namespace bugg {
QList<QUrl> OfficialResourceSource::urls(const QUrl& official, const QUrl&) const {
  const auto host = official.host().toLower();
  if (!official.hasQuery() && !official.hasFragment() && official.path().startsWith("/files/") &&
      (host == "edge.forgecdn.net" || host == "media.forgecdn.net" ||
       host == "mediafilez.forgecdn.net")) {
    auto preferred = official;
    preferred.setHost("mediafilez.forgecdn.net");
    auto fallback = official;
    fallback.setHost("edge.forgecdn.net");
    return {preferred, fallback};
  }
  return {official};
}
}  // namespace bugg
