#include "modules/game_install/infrastructure/bmclapi_resource_source.h"

#include "contracts/download_sources.h"

namespace bugg {
QList<QUrl> BmclapiResourceSource::urls(const QUrl& official, const QUrl&) const {
  if (official.hasQuery() || official.hasFragment()) return {};
  const auto host = official.host().toLower();
  const auto path = official.path();
  QString mapped;
  if ((host == "piston-meta.mojang.com" || host == "launchermeta.mojang.com" ||
       host == "piston-data.mojang.com" || host == "launcher.mojang.com") &&
      (path.startsWith("/mc/") || path.startsWith("/v1/")))
    mapped = path;
  else if (host == "resources.download.minecraft.net")
    mapped = "/assets" + path;
  else if (host == "libraries.minecraft.net" || host == "maven.minecraftforge.net" ||
           host == "maven.fabricmc.net")
    mapped = "/maven" + path;
  else if (host == "meta.fabricmc.net")
    mapped = "/fabric-meta" + path;
  else if (host == "meta.quiltmc.org")
    mapped = "/quilt-meta" + path;
  else if (host == "maven.quiltmc.org" && path.startsWith("/repository/release/"))
    mapped = "/maven/" + path.mid(QString("/repository/release/").size());
  else if (host == "maven.neoforged.net" && path.startsWith("/releases/"))
    mapped = "/maven/" + path.mid(QString("/releases/").size());
  return mapped.isEmpty() ? QList<QUrl>{} : QList<QUrl>{source_url("BMCLAPI", mapped)};
}
}  // namespace bugg
