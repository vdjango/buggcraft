#ifndef BUGG_MODULES_ROOM_SYNC_APPLICATION_ROOM_CONTENT_CACHE_H_
#define BUGG_MODULES_ROOM_SYNC_APPLICATION_ROOM_CONTENT_CACHE_H_
#include <QJsonArray>

#include "contracts/room_content.h"
#include "platform/files/game_files.h"
#include "platform/http/http_client.h"
namespace bugg {
/// 工作线程的房间内容协议适配。原生清单/传输、源站计划共用一个会话与取消标记。
class RoomContentCache {
 public:
  using Progress = std::function<void(const QVariantMap&)>;
  RoomContentCache(RoomContentRequest request, QString session, Cancellation cancelled,
                   Progress progress = {}, HttpClient* transport = nullptr);
  /// 完整分页与原生传输确认；失败/取消撤销 transfer，不保留后台传输。
  QJsonObject transfer(const QString& method, QJsonObject parameters);
  /// 房间声明的计数/摘要与全部分页一致才返回路径归一化的文件；不接受部分清单。
  QJsonArray manifest(const QJsonObject& game);
  /// 来源 resolve 的缓存/公开候选；不可用返回空，由现有公共/P2P 路径继续。
  QList<QUrl> sources(const QJsonObject& item);
  /// 房主持续按源站请求补传文件；进度只采信计划/上传回执，取消后短时释放授权。
  void host(const QString& directory, const QJsonObject& game);

 private:
  QJsonObject grant(bool host);
  QJsonObject query(const QString& path, const QJsonObject& body, bool authorized);
  QJsonObject perform(HttpRequest request, const Cancellation& cancelled);
  void publish(const QString& state, const QString& detail, qint64 done = 0, qint64 total = 0);
  RoomContentRequest request_;
  QString session_;
  Cancellation cancelled_;
  Progress progress_;
  HttpClient http_;
  HttpClient* transport_;
  QJsonObject grant_;
  QVariantMap snapshot_;
  qint64 uploaded_bytes_ = 0;
  qint64 upload_bytes_ = 0;
  bool unavailable_ = false;
};
}  // namespace bugg
#endif
