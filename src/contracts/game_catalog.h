#ifndef BUGG_CONTRACTS_GAME_CATALOG_H_
#define BUGG_CONTRACTS_GAME_CATALOG_H_

#include <QObject>
#include <QString>
#include <QStringList>
#include <QUrl>
#include <QVector>

#include "bugg_contracts_export.h"

namespace bugg {

struct CatalogQuery {
  QString kind = "minecraft";
  QString game_version;
  bool operator==(const CatalogQuery&) const = default;
};

struct CatalogEntry {
  QString id;
  bool stable = true;
  QUrl metadata_url;
  QString sha1;
};

struct CatalogResult {
  QVector<CatalogEntry> entries;
  QString preferred;
  QString source;
  QString error;
};

/// 目录用例端口；GUI 线程调用，结果由 finished 异步返回；不暴露来源格式。
/// request_id 由调用方生成且同一端口内唯一；取消后不得再发该请求的 finished。
class BUGG_CONTRACTS_EXPORT GameCatalogPort : public QObject {
  Q_OBJECT
 public:
  using QObject::QObject;
  virtual void query(quint64 request_id, const CatalogQuery& query) = 0;
  /// 显式刷新绕过缓存有效期；默认调用 query，旧端口实现仍可复用。
  virtual void refresh(quint64 request_id, const CatalogQuery& query) {
    this->query(request_id, query);
  }
  virtual void cancel(quint64 request_id) = 0;
  /// 更新来源优先级；非法值忽略，同值幂等，成功后通知会话刷新旧目录。
  Q_INVOKABLE virtual void select_sources(const QStringList& order, const QUrl& bugg_base = {}) = 0;
 signals:
  void source_selection_changed();
  /// 与 query 相同线程；实际发出请求时报告源，取消后不再通知该 ID。
  void source_changed(quint64 request_id, const QString& source);
  /// 可选的本地成功快照；不结束请求，随后仍只发一次 finished；取消后不再通知。
  void cached(quint64 request_id, const bugg::CatalogResult& result);
  void finished(quint64 request_id, const bugg::CatalogResult& result);
};

}  // namespace bugg

#endif  // BUGG_CONTRACTS_GAME_CATALOG_H_
