#include "modules/game_install/infrastructure/bugg_resource_source.h"

#include "contracts/download_sources.h"

namespace bugg {
QList<QUrl> BuggResourceSource::urls(const QUrl& official, const QUrl& bugg_base) const {
  const auto host = official.host().toLower();
  const auto path = official.path();
  const bool metadata = host == "api.curseforge.com" || host == "api.modrinth.com";
  if ((official.hasQuery() || official.hasFragment()) && !metadata) return {};
  QString mapped;
  if (host == "api.curseforge.com" && path.startsWith("/v1/"))
    mapped = "/v1/catalog/curseforge" + path.mid(3);
  else if (host == "api.modrinth.com" && path.startsWith("/v2/"))
    mapped = "/v1/catalog/modrinth" + path.mid(3);
  else if ((host == "piston-meta.mojang.com" || host == "launchermeta.mojang.com" ||
            host == "piston-data.mojang.com" || host == "launcher.mojang.com") &&
           (path.startsWith("/mc/") || path.startsWith("/v1/")))
    mapped = path;
  else if (host == "resources.download.minecraft.net")
    mapped = "/assets" + path;
  else if (host == "libraries.minecraft.net" || host == "maven.minecraftforge.net")
    mapped = "/maven" + path;
  else if (host == "meta.fabricmc.net")
    mapped = "/fabric-meta" + path;
  else if (host == "meta.quiltmc.org")
    mapped = "/quilt-meta" + path;
  else if (host == "maven.fabricmc.net")
    mapped = "/fabric-maven" + path;
  else if (host == "maven.quiltmc.org" && path.startsWith("/repository/release/"))
    mapped = "/quilt-maven" + path;
  else if (host == "maven.neoforged.net" && path.startsWith("/releases/"))
    mapped = "/neoforge-maven" + path;
  else if (host == "cdn.modrinth.com" && path.startsWith("/data/"))
    mapped = "/mods/modrinth" + path;
  else if (path.startsWith("/files/") &&
           (host == "edge.forgecdn.net" || host == "mediafilez.forgecdn.net" ||
            host == "media.forgecdn.net")) {
    // Both routes retain Bugg cache priority; the first has demonstrated valid Range support.
    return {source_url("BUGG", "/mods/curseforge-mediafilez" + path, bugg_base),
            source_url("BUGG", "/mods/curseforge" + path, bugg_base)};
  }
  if (mapped.isEmpty()) return {};
  auto url = source_url("BUGG", mapped, bugg_base);
  if (metadata) url.setQuery(official.query());
  return {url};
}
}  // namespace bugg
