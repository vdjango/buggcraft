#ifndef BUGG_CONTRACTS_DOWNLOAD_SOURCES_H_
#define BUGG_CONTRACTS_DOWNLOAD_SOURCES_H_

#include <QString>
#include <QStringList>
#include <QUrl>
#include <QVector>

#include "bugg_contracts_export.h"

namespace bugg {

/// 唯一 Bugg 默认入口；配置由 SourceSettings 持有，工作线程只接收值快照。
BUGG_CONTRACTS_EXPORT QUrl default_bugg_source();
/// Official public file path fallback; callers enforce metadata/access policy.
BUGG_CONTRACTS_EXPORT QString curseforge_file_url(qint64 id, const QString& filename,
                                                  const QString& provided);
/// 纯 URL 拼接，保留基址路径前缀；仅支持 BUGG/BMCLAPI，其他来源返回空。
BUGG_CONTRACTS_EXPORT QUrl source_url(const QString& source, const QString& path,
                                      const QUrl& bugg_base = default_bugg_source());

/// 远端提供的协议能力，不代表客户端对应业务已经接入。
enum class SourceCapability {
  MinecraftCatalog,
  ForgeCatalog,
  NeoForgeCatalog,
  FabricCatalog,
  QuiltCatalog,
  CurseForgeContent,
  ModrinthContent,
  GameResources,
};

struct SourceDefinition {
  QString id;
  QVector<SourceCapability> capabilities;
  QString supplement;
};

struct SourceRoute {
  QString selected;
  QString actual;
  QString reason;
  QString error;
};

struct SourcePlan {
  QVector<SourceRoute> routes;
  QString error;
};

/// 唯一能力登记；首项 BUGG 是新配置默认值。不包含网络可用性探测结果。
BUGG_CONTRACTS_EXPORT const QVector<SourceDefinition>& download_sources();
BUGG_CONTRACTS_EXPORT QStringList supported_download_sources();
/// 纯值决策，可跨线程调用，无 I/O、无重试；未知来源/能力返回 error。
/// 只有明确未登记的能力使用一个补齐源；请求失败不得调用它重新选源。
BUGG_CONTRACTS_EXPORT SourceRoute resolve_source(const QString& selected,
                                                 SourceCapability capability);
/// 按用户优先级展开能力补齐并去重实际源；允许子集用于受控请求/测试。
/// 空队列、重复或未知来源失败；不因网络结果更改计划。
BUGG_CONTRACTS_EXPORT SourcePlan resolve_sources(const QStringList& order,
                                                 SourceCapability capability);

}  // namespace bugg
#endif  // BUGG_CONTRACTS_DOWNLOAD_SOURCES_H_
