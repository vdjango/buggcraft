#include "modules/catalog/application/game_catalog_service.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QFutureWatcher>
#include <QLoggingCategory>
#include <QTimer>
#include <QtConcurrent/QtConcurrentRun>

#include "modules/catalog/infrastructure/game_catalog_provider.h"
#include "platform/http/http_client.h"

namespace bugg {
namespace {
Q_LOGGING_CATEGORY(catalog_log, "bugg.catalog")
}

GameCatalogService::GameCatalogService(HttpClient* transport, QStringList order, QObject* parent,
                                       QString cache_path)
    : GameCatalogPort(parent),
      transport_(transport),
      order_(std::move(order)),
      cache_(std::move(cache_path)) {
  connect(&cache_, &CatalogCache::loaded, this, [this] {
    const auto ids = active_.keys();
    for (const auto id : ids) resume(id);
  });
  connect(transport_, &HttpClient::completed, this,
          [this](quint64 wire_id, const QByteArray& body, const QString& error) {
            if (!requests_.contains(wire_id)) return;
            const auto id = requests_.take(wire_id);
            if (!active_.contains(id) || active_[id].transport_id != wire_id) return;
            if (!error.isEmpty()) {
              CatalogResult result;
              result.error = error;
              accept(id, wire_id, result);
              return;
            }
            const auto query = active_[id].query;
            const auto provider = active_[id].providers[active_[id].source_index];
            auto* watcher = new QFutureWatcher<CatalogResult>(this);
            connect(watcher, &QFutureWatcher<CatalogResult>::finished, this,
                    [this, watcher, id, wire_id] {
                      const auto result = watcher->result();
                      watcher->deleteLater();
                      accept(id, wire_id, result);
                    });
            // 值捕获，不访问窗口/页面；销毁 watcher 不等待独立的纯解析工作。
            watcher->setFuture(QtConcurrent::run(
                [provider, query, body] { return provider->parse(query, body); }));
          });
}

GameCatalogService::~GameCatalogService() {
  const auto ids = active_.keys();
  for (const auto id : ids) cancel(id);
}

void GameCatalogService::query(quint64 request_id, const CatalogQuery& query) {
  start(request_id, query, false);
}

void GameCatalogService::refresh(quint64 request_id, const CatalogQuery& query) {
  start(request_id, query, true);
}

void GameCatalogService::start(quint64 request_id, const CatalogQuery& query, bool force_refresh) {
  cancel(request_id);
  const auto generation = ++generation_;
  active_.insert(request_id, {query,
                              0,
                              0,
                              generation,
                              {},
                              default_catalog_providers(order_, query, bugg_base_),
                              force_refresh});
  QTimer::singleShot(0, this, [this, request_id, generation] {
    if (active_.contains(request_id) && active_[request_id].generation == generation)
      resume(request_id);
  });
}

void GameCatalogService::resume(quint64 request_id) {
  if (!cache_.ready() || !active_.contains(request_id) || active_[request_id].transport_id) return;
  const auto& op = active_[request_id];
  const auto key = CatalogCache::key(order_, op.query, bugg_base_);
  const auto snapshot = cache_.lookup(key);
  const auto generation = op.generation;
  if (!op.force_refresh && checked_until_.value(key) > QDateTime::currentMSecsSinceEpoch()) {
    const auto previous = snapshot                       ? snapshot
                          : recent_errors_.contains(key) ? std::optional(recent_errors_.value(key))
                                                         : std::nullopt;
    if (previous) {
      active_.remove(request_id);
      emit finished(request_id, *previous);
      return;
    }
  }
  if (snapshot) {
    emit cached(request_id, *snapshot);
  }
  // cached 的订阅者可能取消或切源，不能继续使用之前的引用。
  if (active_.contains(request_id) && active_[request_id].generation == generation)
    attempt(request_id);
}

void GameCatalogService::complete(quint64 request_id, const CatalogResult& result) {
  if (!active_.contains(request_id)) return;
  const auto key = CatalogCache::key(order_, active_.take(request_id).query, bugg_base_);
  checked_until_[key] =
      QDateTime::currentMSecsSinceEpoch() + (result.error.isEmpty() ? 10 * 60 * 1000 : 60 * 1000);
  if (result.error.isEmpty()) {
    recent_errors_.remove(key);
    cache_.store(key, result);
  } else {
    recent_errors_[key] = result;
  }
  emit finished(request_id, result);
}

void GameCatalogService::cancel(quint64 request_id) {
  if (!active_.contains(request_id)) return;
  const auto wire_id = active_.take(request_id).transport_id;
  requests_.remove(wire_id);
  if (wire_id) transport_->cancel(wire_id);
}

void GameCatalogService::select_sources(const QStringList& order, const QUrl& bugg_base) {
  const auto base = bugg_base.isEmpty() ? bugg_base_ : bugg_base;
  if ((order == order_ && base == bugg_base_) ||
      !resolve_sources(order, SourceCapability::MinecraftCatalog).error.isEmpty())
    return;
  const auto ids = active_.keys();
  for (const auto id : ids) cancel(id);
  order_ = order;
  bugg_base_ = base;
  emit source_selection_changed();
}

void GameCatalogService::attempt(quint64 request_id) {
  if (!active_.contains(request_id)) return;
  auto& op = active_[request_id];
  if (op.source_index >= op.providers.size()) {
    CatalogResult result;
    if (!op.providers.empty()) result.source = op.providers.back()->id();
    if (!op.errors.isEmpty() || op.providers.empty())
      result.error = QCoreApplication::translate("Bugg", "版本目录获取失败，请重试。\n") +
                     op.errors.join("\n");
    complete(request_id, result);
    return;
  }
  const auto source = op.providers[op.source_index]->id();
  const auto url = op.providers[op.source_index]->request_url(op.query);
  qCInfo(catalog_log).noquote() << "request" << request_id << source << url.toString();
  // 先登记传输，再通知界面；订阅者在通知中取消时仍可撤销这次请求。
  op.transport_id = transport_->get(url, op.providers[op.source_index]->blocked_redirect_hosts());
  requests_.insert(op.transport_id, request_id);
  emit source_changed(request_id, source);
}

void GameCatalogService::accept(quint64 request_id, quint64 transport_id,
                                const CatalogResult& result) {
  if (!active_.contains(request_id) || active_[request_id].transport_id != transport_id) return;
  if (!result.error.isEmpty() || result.entries.isEmpty()) {
    auto& op = active_[request_id];
    const auto error = op.providers[op.source_index]->id() + " · " +
                       (result.error.isEmpty() ? QCoreApplication::translate("Bugg", "没有兼容版本")
                                               : result.error);
    qCInfo(catalog_log).noquote() << "failed" << request_id << error;
    if (!result.error.isEmpty()) op.errors.push_back(error);
    ++op.source_index;
    attempt(request_id);
    return;
  }
  qCInfo(catalog_log).noquote() << "ready" << request_id << result.source << result.entries.size();
  complete(request_id, result);
}

}  // namespace bugg
