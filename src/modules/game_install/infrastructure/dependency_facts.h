#ifndef BUGG_MODULES_GAME_INSTALL_INFRASTRUCTURE_DEPENDENCY_FACTS_H_
#define BUGG_MODULES_GAME_INSTALL_INFRASTRUCTURE_DEPENDENCY_FACTS_H_
#include <QJsonArray>

#include "modules/game_install/infrastructure/resource_client.h"

namespace bugg {
/// Worker-owned adapter. Hashes concrete active JARs, queries the configured
/// source in batches, falls back to bounded native metadata reads. One task,
/// cancellation owner, HTTP client and content cache; never executes a JAR.
class DependencyFacts {
 public:
  DependencyFacts(QString cache, ResourceClient& resources, QUrl source, Cancellation cancelled);
  /// relative path -> concrete staged/installed file. Maximum 4096 active JARs.
  /// Returns content-addressed versioned facts; failures/cancellation throw.
  QJsonArray collect(const QMap<QString, QString>& files);

 private:
  QJsonObject parse(const QString& path, const QString& digest, qint64 size);
  QString cache_;
  ResourceClient& resources_;
  QUrl source_;
  Cancellation cancelled_;
  bool source_available_ = true;
};
}  // namespace bugg
#endif
