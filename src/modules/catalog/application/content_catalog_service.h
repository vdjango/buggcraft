#ifndef BUGG_MODULES_CATALOG_APPLICATION_CONTENT_CATALOG_SERVICE_H_
#define BUGG_MODULES_CATALOG_APPLICATION_CONTENT_CATALOG_SERVICE_H_
#include <QCache>
#include <QHash>

#include "contracts/content_catalog.h"
#include "modules/catalog/infrastructure/content_provider.h"

namespace bugg {
/// Application-owned content queries. GUI methods, worker-only HTTP/parsing,
/// bounded successful cache; shutdown cancels without blocking the GUI.
class ContentCatalogService final : public ContentCatalogPort {
  Q_OBJECT
 public:
  explicit ContentCatalogService(QObject* parent = nullptr, ContentEndpoints endpoints = {});
  ~ContentCatalogService() override;
  void query(quint64 id, const QVariantMap& query) override;
  void cancel(quint64 id) override;
  void select_sources(const QStringList& order, const QUrl& bugg_base = {});
  /// Worker query callback captures only values, independent of this QObject.
  ContentRequest requester() const;
  void shutdown();
  bool busy() const { return workers_ != 0; }
 signals:
  void drained();

 private:
  struct Cached {
    QVariantMap value;
    qint64 expires;
  };
  struct Pending {
    quint64 generation;
    std::shared_ptr<std::atomic_bool> cancelled;
  };
  ContentEndpoints endpoints_;
  QStringList order_ = supported_download_sources();
  QHash<quint64, Pending> active_;
  QHash<QByteArray, qint64> translation_ensured_;
  QCache<QByteArray, Cached> cache_{8 * 1024};
  quint64 sequence_ = 0;
  int workers_ = 0;
  bool closing_ = false;
};
}  // namespace bugg
#endif
