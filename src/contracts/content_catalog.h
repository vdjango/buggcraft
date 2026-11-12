#ifndef BUGG_CONTRACTS_CONTENT_CATALOG_H_
#define BUGG_CONTRACTS_CONTENT_CATALOG_H_
#include <QObject>
#include <QVariantMap>
#include <atomic>
#include <functional>
#include <memory>

#include "bugg_contracts_export.h"

namespace bugg {
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
};
}  // namespace bugg
#endif
