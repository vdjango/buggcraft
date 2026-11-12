#include "modules/catalog/application/content_catalog_service.h"

#include <QDateTime>
#include <QFutureWatcher>
#include <QJsonDocument>
#include <QTimer>
#include <QtConcurrent/QtConcurrentRun>

namespace bugg {
ContentCatalogService::ContentCatalogService(QObject* parent, ContentEndpoints endpoints)
    : ContentCatalogPort(parent), endpoints_(std::move(endpoints)) {
  if (endpoints_.curseforge_key.isEmpty())
    endpoints_.curseforge_key = qgetenv("BUGGCRAFT_CURSEFORGE_API_KEY");
}
ContentCatalogService::~ContentCatalogService() { shutdown(); }
ContentRequest ContentCatalogService::requester() const {
  return [order = order_, endpoints = endpoints_](const QVariantMap& query, const auto& cancelled) {
    return request_content(query, order, endpoints, cancelled);
  };
}
void ContentCatalogService::query(quint64 id, const QVariantMap& query) {
  cancel(id);
  if (closing_) return;
  const auto generation = ++sequence_;
  const auto cancelled = std::make_shared<std::atomic_bool>(false);
  active_[id] = {generation, cancelled};
  auto effective_query = query;
  QByteArray ensure_key;
  if (query.value("operation") == "translations" && query.value("ensure").toBool()) {
    auto lookup = query;
    lookup["ensure"] = false;
    ensure_key = QJsonDocument::fromVariant(lookup).toJson(QJsonDocument::Compact);
    if (translation_ensured_.value(ensure_key, 0) > QDateTime::currentMSecsSinceEpoch())
      effective_query["ensure"] = false;
    else
      translation_ensured_.remove(ensure_key);
  }
  const auto key = QJsonDocument::fromVariant(effective_query).toJson(QJsonDocument::Compact);
  if (const auto record = cache_.object(key);
      record && record->expires > QDateTime::currentMSecsSinceEpoch()) {
    const auto value = record->value;
    QTimer::singleShot(0, this, [this, id, generation, value] {
      if (!active_.contains(id) || active_[id].generation != generation) return;
      active_.remove(id);
      emit finished(id, value);
    });
    return;
  }
  ++workers_;
  auto* watcher = new QFutureWatcher<QVariantMap>(this);
  connect(
      watcher, &QFutureWatcherBase::finished, this,
      [this, watcher, id, key, ensure_key, generation] {
        auto value = watcher->result();
        watcher->deleteLater();
        --workers_;
        if (active_.contains(id) && active_[id].generation == generation) {
          active_.remove(id);
          if (value.contains("_translationToken")) {
            endpoints_.translation_token = value.take("_translationToken").toByteArray();
            endpoints_.translation_token_expires = value.take("_translationExpires").toLongLong();
          }
          if (value.contains("_ensured")) {
            if (translation_ensured_.size() >= 64) translation_ensured_.clear();
            translation_ensured_[ensure_key] = QDateTime::currentMSecsSinceEpoch() + 5 * 60 * 1000;
            value.remove("_ensured");
          }
          if (!value.contains("error")) {
            if (cache_.size() >= 64) cache_.clear();
            const int cost = qMax(
                1, int((QJsonDocument::fromVariant(value).toJson(QJsonDocument::Compact).size() +
                        1023) /
                       1024));
            const bool polling = value.value("pending").toBool();
            const bool translation = value.contains("translations");
            const int ttl = translation ? (polling ? 0 : 15000) : 5 * 60 * 1000;
            cache_.insert(key, new Cached{value, QDateTime::currentMSecsSinceEpoch() + ttl}, cost);
          }
          emit finished(id, value);
        }
        if (closing_ && !busy()) emit drained();
      });
  watcher->setFuture(QtConcurrent::run([request = requester(), query = effective_query, cancelled] {
    try {
      return request(query, cancelled);
    } catch (const std::exception& error) {
      return QVariantMap{{"error", QString::fromUtf8(error.what())}};
    }
  }));
}
void ContentCatalogService::cancel(quint64 id) {
  if (active_.contains(id)) active_.take(id).cancelled->store(true);
}
void ContentCatalogService::select_sources(const QStringList& order, const QUrl& bugg_base) {
  const auto base = bugg_base.isEmpty() ? endpoints_.bugg_base : bugg_base;
  if ((order == order_ && base == endpoints_.bugg_base) ||
      !resolve_sources(order, SourceCapability::ModrinthContent).error.isEmpty())
    return;
  const auto ids = active_.keys();
  for (auto id : ids) cancel(id);
  cache_.clear();
  order_ = order;
  endpoints_.bugg_base = base;
  endpoints_.translation_token.clear();
  endpoints_.translation_token_expires = 0;
  translation_ensured_.clear();
  emit source_selection_changed();
}
void ContentCatalogService::shutdown() {
  closing_ = true;
  const auto ids = active_.keys();
  for (auto id : ids) cancel(id);
}
}  // namespace bugg
