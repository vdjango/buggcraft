#ifndef BUGG_MODULES_CATALOG_APPLICATION_GAME_CATALOG_SERVICE_H_
#define BUGG_MODULES_CATALOG_APPLICATION_GAME_CATALOG_SERVICE_H_

#include <QHash>
#include <QStringList>
#include <memory>
#include <vector>

#include "contracts/download_sources.h"
#include "contracts/game_catalog.h"
#include "modules/catalog/infrastructure/catalog_cache.h"

namespace bugg {
class HttpClient;
class GameCatalogProvider;

/// GUI 线程协调目录查询；网络异步，解析在有界 Qt 全局线程池。
/// app 注入统一优先级；transport 必须比服务活得久，适配器由请求持有。
class GameCatalogService final : public GameCatalogPort {
  Q_OBJECT
 public:
  GameCatalogService(HttpClient* transport, QStringList order = supported_download_sources(),
                     QObject* parent = nullptr, QString cache_path = {});
  ~GameCatalogService() override;
  /// 同 ID 新查询先取消旧查询；优先复用有效缓存，否则先发快照再后台更新。
  void query(quint64 request_id, const CatalogQuery& query) override;
  /// 显式重取，绕过有效期/失败冷却；仍保留已有缓存快照供界面使用。
  void refresh(quint64 request_id, const CatalogQuery& query) override;
  /// 即刻撤销活动记录，迟到网络/解析结果无效；无同步等待。
  void cancel(quint64 request_id) override;
  void select_sources(const QStringList& order, const QUrl& bugg_base = {}) override;

  void relocate_storage(const QString& path) { cache_.relocate_storage(path); }

 private:
  struct Operation {
    CatalogQuery query;
    size_t source_index = 0;
    quint64 transport_id = 0;
    quint64 generation = 0;
    QStringList errors;
    std::vector<std::shared_ptr<const GameCatalogProvider>> providers;
    bool force_refresh = false;
  };
  void start(quint64 request_id, const CatalogQuery& query, bool force_refresh);
  void resume(quint64 request_id);
  void complete(quint64 request_id, const CatalogResult& result);
  void attempt(quint64 request_id);
  void accept(quint64 request_id, quint64 transport_id, const CatalogResult& result);
  HttpClient* transport_;
  QStringList order_;
  QUrl bugg_base_ = default_bugg_source();
  CatalogCache cache_;
  QHash<QString, qint64> checked_until_;
  QHash<QString, CatalogResult> recent_errors_;
  QHash<quint64, Operation> active_;
  QHash<quint64, quint64> requests_;
  quint64 generation_ = 0;
};

}  // namespace bugg
#endif  // BUGG_MODULES_CATALOG_APPLICATION_GAME_CATALOG_SERVICE_H_
