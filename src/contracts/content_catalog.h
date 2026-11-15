#ifndef BUGG_CONTRACTS_CONTENT_CATALOG_H_
#define BUGG_CONTRACTS_CONTENT_CATALOG_H_
#include <QObject>
#include <QStringList>
#include <QVariantMap>
#include <atomic>
#include <functional>
#include <memory>

#include "bugg_contracts_export.h"

namespace bugg {
/// Shared target policy; actual JAR dependencies still require separate checks.
inline QStringList content_loader_formats(const QString& loader, const QString& game) {
  QStringList formats{loader};
  if (loader == "quilt") formats.append("fabric");
  if (loader == "neoforge" && game == "1.20.1") formats.append("forge");
  return formats;
}
/// Worker-only value port. Throws on network/metadata failure or cancellation;
/// captures a source snapshot, never a page or GUI QObject.
using ContentRequest =
    std::function<QVariantMap(const QVariantMap&, const std::shared_ptr<std::atomic_bool>&)>;

/// GUI asynchronous content directory. IDs are caller-owned; cancellation
/// suppresses late completion. Normalized values contain no credentials.
class BUGG_CONTRACTS_EXPORT ContentCatalogPort : public QObject {
  Q_OBJECT
 public:
  using QObject::QObject;
  virtual void query(quint64 id, const QVariantMap& query) = 0;
  virtual void cancel(quint64 id) = 0;
 signals:
  void finished(quint64 id, const QVariantMap& result);
  void source_selection_changed();
  /// GUI: a confirmed report invalidates shader feedback snapshots and pending plans.
  void feedback_changed();
};
}  // namespace bugg
#endif
