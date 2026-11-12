#ifndef BUGG_MODULES_ACCOUNT_APPLICATION_MICROSOFT_ACCOUNT_H_
#define BUGG_MODULES_ACCOUNT_APPLICATION_MICROSOFT_ACCOUNT_H_
#include <QDateTime>
#include <QJsonObject>
#include <QTimer>

#include "contracts/game_runtime.h"
#include "platform/http/http_client.h"
namespace bugg {
/// 真实设备码 → Xbox → Minecraft 会话；令牌不进入 QML/日志。应用寿命，GUI 异步网络。
class MicrosoftAccount : public AccountPort {
  Q_OBJECT
 public:
  explicit MicrosoftAccount(HttpClient* http, QString credential_path, QObject* parent = nullptr);
  void restore();
  void begin() override;
  void cancel() override;
  void logout() override;
  void acquire(quint64 operation, const QString& profile_id) override;
  bool busy() const {
    return storage_busy_ || restore_reading_ || restoring_ || request_id_ || polling_.isActive();
  }
  /// GUI 迁移后重定向唯一写入队列，保存当前最新快照。
  void relocate_storage(const QString& path);
 signals:
  void restored(const QString& error);
  void storage_error(const QString& error);

 private:
  enum class Step { Device, Poll, Refresh, Xbox, Xsts, Minecraft, Profile };
  void send(Step step, const QUrl& url, const QJsonObject& json = {}, bool form = false);
  void received(const QByteArray& body, const QString& error, int status);
  void poll();
  void fail(const QString& error);
  void persist();
  QString client_id_;
  QString path_;
  HttpClient* http_;
  quint64 request_id_ = 0;
  quint64 generation_ = 0;
  Step step_ = Step::Device;
  QTimer polling_;
  QString device_code_, refresh_token_, microsoft_token_, xbox_token_, user_hash_;
  GameIdentity identity_;
  QDateTime expires_, device_expires_;
  int interval_ms_ = 5000;
  QList<quint64> waiting_;
  bool restoring_ = false;
  bool restore_reading_ = false;
  bool storage_busy_ = false;
  bool storage_pending_ = false;
};
}  // namespace bugg
#endif
