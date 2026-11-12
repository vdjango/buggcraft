#include "contracts/download_sources.h"

#include <QCoreApplication>
#include <algorithm>

namespace bugg {
QString curseforge_file_url(qint64 id, const QString& filename, const QString& provided) {
  if (!provided.isEmpty()) return provided;
  if (id <= 0 || filename.isEmpty() || filename.contains('/') || filename.contains('\\')) return {};
  return "https://edge.forgecdn.net/files/" + QString::number(id / 1000) + '/' +
         QString::number(id % 1000) + '/' + QString::fromLatin1(QUrl::toPercentEncoding(filename));
}

QUrl default_bugg_source() { return QUrl("https://mirror.bugg.icu"); }

QUrl source_url(const QString& source, const QString& path, const QUrl& bugg_base) {
  auto base = source == "BUGG"      ? bugg_base
              : source == "BMCLAPI" ? QUrl("https://bmclapi2.bangbang93.com")
                                    : QUrl{};
  if (base.isEmpty()) return {};
  auto prefix = base.path();
  while (prefix.endsWith('/')) prefix.chop(1);
  base.setPath(prefix + path);
  return base;
}

const QVector<SourceDefinition>& download_sources() {
  static const QVector<SourceCapability> game = {
      SourceCapability::MinecraftCatalog, SourceCapability::ForgeCatalog,
      SourceCapability::NeoForgeCatalog,  SourceCapability::FabricCatalog,
      SourceCapability::QuiltCatalog,     SourceCapability::GameResources};
  static const auto all = [] {
    auto capabilities = game;
    capabilities.append(SourceCapability::CurseForgeContent);
    capabilities.append(SourceCapability::ModrinthContent);
    return capabilities;
  }();
  static const QVector<SourceDefinition> sources = {
      {"BUGG", all, {}}, {"BMCLAPI", game, "官方"}, {"官方", all, {}}};
  return sources;
}

QStringList supported_download_sources() {
  QStringList ids;
  for (const auto& source : download_sources()) ids.append(source.id);
  return ids;
}

SourceRoute resolve_source(const QString& selected, SourceCapability capability) {
  const auto& sources = download_sources();
  const auto preferred = std::find_if(sources.begin(), sources.end(),
                                      [&](const auto& item) { return item.id == selected; });
  if (preferred == sources.end())
    return {selected, {}, {}, QCoreApplication::translate("Bugg", "未知下载源")};
  if (preferred->capabilities.contains(capability)) return {selected, selected, {}, {}};
  const auto supplement = std::find_if(sources.begin(), sources.end(), [&](const auto& item) {
    return item.id == preferred->supplement && item.capabilities.contains(capability);
  });
  if (supplement == sources.end())
    return {selected,
            {},
            {},
            QCoreApplication::translate("Bugg", "所选源未提供此能力，且无可用补齐源")};
  return {selected,
          supplement->id,
          selected + QCoreApplication::translate("Bugg", " 未提供此能力，使用") + supplement->id,
          {}};
}

SourcePlan resolve_sources(const QStringList& order, SourceCapability capability) {
  if (order.isEmpty()) return {{}, QCoreApplication::translate("Bugg", "下载源优先级为空")};
  SourcePlan plan;
  QStringList selected;
  QStringList actual;
  for (const auto& id : order) {
    if (selected.contains(id))
      return {{}, QCoreApplication::translate("Bugg", "下载源优先级包含重复来源")};
    selected.append(id);
    const auto route = resolve_source(id, capability);
    if (!route.error.isEmpty()) return {{}, route.error};
    if (!actual.contains(route.actual)) {
      actual.append(route.actual);
      plan.routes.append(route);
    }
  }
  return plan;
}

}  // namespace bugg
