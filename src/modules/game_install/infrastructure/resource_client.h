#ifndef BUGG_MODULES_GAME_INSTALL_INFRASTRUCTURE_RESOURCE_CLIENT_H_
#define BUGG_MODULES_GAME_INSTALL_INFRASTRUCTURE_RESOURCE_CLIENT_H_
#include <QJsonObject>
#include <QUrl>
#include <QVariantMap>
#include <functional>

#include "contracts/download_sources.h"
#include "platform/files/game_files.h"
#include "platform/http/http_client.h"

namespace bugg {
struct GameResource {
  QUrl url;
  QString path;
  QByteArray sha1;
  qint64 size = -1;
  QList<QUrl> alternatives;
  QString group;
};
/// 唯一官方 URL → 各源地址映射；不认识的能力只走官方，实际 URL 去重。
QList<QUrl> resource_urls(const QUrl& official, const QStringList& source_order,
                          const QUrl& bugg_base = default_bugg_source());
/// 工作线程拥有的资源批次；每资源组使用设置并发，校验缓存、逐源回退和取消。
class ResourceClient {
 public:
  using Progress = std::function<void(double, const QString&)>;
  using TransferProgress = std::function<void(const QVariantMap&)>;
  /// transport 可注入同线程客户端，须比本对象长寿；空时使用自身 HTTP 客户端。
  ResourceClient(QStringList source_order, Cancellation cancelled, Progress progress,
                 HttpClient* transport = nullptr, int concurrency = 6,
                 QUrl bugg_base = default_bugg_source());
  ~ResourceClient();
  QJsonObject json(const QUrl& official, const QJsonObject& body = {});
  QJsonObject json(const QUrl& official, const QJsonObject& body, int budget_ms, int retries);
  /// Metadata batch, bounded by the same configured concurrency, URL deduped.
  QHash<QUrl, QJsonObject> json_many(const QList<QUrl>& official, const QJsonObject& body = {});
  /// Optional batches retain successes and bound the entire lookup by budget_ms;
  /// expiry cancels outstanding queries. Required batches remain fail-fast.
  QHash<QUrl, QJsonObject> json_many(const QList<QUrl>& official, const QJsonObject& body,
                                     int budget_ms, int retries, Progress batch_progress = {},
                                     bool continue_on_error = false);
  /// Worker-only file snapshots; uses the same batch/HTTP/cancellation owner.
  void set_transfer_progress(TransferProgress progress) {
    transfer_progress_ = std::move(progress);
  }
  /// Defaults to fail-fast. Independent content dependencies may collect errors
  /// by path while the other files finish; cancellation always throws.
  QHash<QString, QString> fetch(const QList<GameResource>& resources,
                                bool continue_on_error = false);
  /// Worker-owned expansion after a cached or downloaded file is verified.
  /// Discovered files join this same queue; callback failures cancel the batch.
  QHash<QString, QString> fetch(
      const QList<GameResource>& resources, bool continue_on_error,
      const std::function<QList<GameResource>(const GameResource&)>& expand,
      Progress batch_progress = {});

 private:
  QStringList source_order_;
  QUrl bugg_base_;
  Cancellation cancelled_;
  Progress progress_;
  TransferProgress transfer_progress_;
  HttpClient http_;
  HttpClient* transport_;
  int concurrency_;
};
}  // namespace bugg
#endif
