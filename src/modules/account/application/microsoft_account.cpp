#include "modules/account/application/microsoft_account.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QUrlQuery>
#include <QUuid>
#include <QtConcurrent/QtConcurrentRun>

#include "modules/account/infrastructure/credential_store.h"

namespace bugg {
namespace {
const QString kAuthority = "https://login.microsoftonline.com/consumers/oauth2/v2.0/";
const QString kScope = "XboxLive.signin offline_access";
}  // namespace
MicrosoftAccount::MicrosoftAccount(HttpClient* http, QString credential_path, QObject* parent)
    : AccountPort(parent),
      client_id_(qEnvironmentVariable("BUGGCRAFT_MICROSOFT_CLIENT_ID",
                                      "9372e575-a673-4100-bed9-b5d2e4023d30")),
      path_(std::move(credential_path)),
      http_(http) {
  polling_.setSingleShot(true);
  connect(&polling_, &QTimer::timeout, this, &MicrosoftAccount::poll);
  connect(http_, &HttpClient::response, this,
          [this](quint64 id, const QByteArray& body, const QString& error, int status) {
            if (id != request_id_) return;
            request_id_ = 0;
            received(body, error, status);
          });
}
void MicrosoftAccount::restore() {
  if (restore_reading_ || restoring_) return;
  restore_reading_ = true;
  restoring_ = true;
  const auto generation = generation_;
  auto* watcher = new QFutureWatcher<QPair<QByteArray, QString>>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher, generation] {
    const auto [payload, error] = watcher->result();
    watcher->deleteLater();
    restore_reading_ = false;
    if (generation != generation_) {
      emit restored({});
      return;
    }
    const auto stored = QJsonDocument::fromJson(payload).object();
    refresh_token_ = stored["refresh"].toString();
    identity_.name = stored["name"].toString();
    identity_.uuid = stored["uuid"].toString();
    if (!refresh_token_.isEmpty()) {
      restoring_ = true;
      send(Step::Refresh, QUrl(kAuthority + "token"),
           {{"client_id", client_id_},
            {"grant_type", "refresh_token"},
            {"refresh_token", refresh_token_},
            {"scope", kScope}},
           true);
    } else {
      restoring_ = false;
      emit restored(error);
    }
  });
  watcher->setFuture(QtConcurrent::run([path = path_] {
    try {
      return qMakePair(load_credentials(path), QString());
    } catch (const std::exception& error) {
      return qMakePair(QByteArray(), QString::fromUtf8(error.what()));
    }
  }));
}
void MicrosoftAccount::begin() {
  cancel();
  emit authentication("authorizing", {}, {});
  send(Step::Device, QUrl(kAuthority + "devicecode"),
       {{"client_id", client_id_}, {"scope", kScope}}, true);
}
void MicrosoftAccount::cancel() {
  ++generation_;
  if (request_id_) http_->cancel(request_id_);
  request_id_ = 0;
  polling_.stop();
  device_code_.clear();
  const auto waiting = std::exchange(waiting_, {});
  for (auto id : waiting)
    emit credentials_ready(id, {}, QCoreApplication::translate("Bugg", "授权已取消"));
  if (restoring_) {
    restoring_ = false;
    emit restored(QCoreApplication::translate("Bugg", "身份恢复已取消"));
  }
  emit authentication("idle", {}, {});
}
void MicrosoftAccount::logout() {
  cancel();
  identity_ = {};
  refresh_token_.clear();
  microsoft_token_.clear();
  xbox_token_.clear();
  user_hash_.clear();
  persist();
}
void MicrosoftAccount::acquire(quint64 operation, const QString& profile_id) {
  if (profile_id.startsWith("offline:")) {
    const auto name = profile_id.mid(8);
    if (!QRegularExpression("\\A[A-Za-z0-9_]{3,16}\\z").match(name).hasMatch()) {
      emit credentials_ready(operation, {}, QCoreApplication::translate("Bugg", "离线名称无效"));
      return;
    }
    auto uuid =
        QCryptographicHash::hash(("OfflinePlayer:" + name).toUtf8(), QCryptographicHash::Md5);
    uuid[6] = char((uchar(uuid[6]) & 0x0f) | 0x30);
    uuid[8] = char((uchar(uuid[8]) & 0x3f) | 0x80);
    emit credentials_ready(
        operation, {name, QString::fromLatin1(uuid.toHex()), {}, "offline", {}, client_id_}, {});
    return;
  }
  if (profile_id != "microsoft:" + identity_.name || refresh_token_.isEmpty()) {
    emit credentials_ready(operation, {},
                           QCoreApplication::translate("Bugg", "请重新登录微软账号"));
    return;
  }
  if (!identity_.access_token.isEmpty() &&
      expires_ > QDateTime::currentDateTimeUtc().addSecs(120)) {
    emit credentials_ready(operation, identity_, {});
    return;
  }
  waiting_.append(operation);
  if (request_id_ || polling_.isActive()) return;
  send(Step::Refresh, QUrl(kAuthority + "token"),
       {{"client_id", client_id_},
        {"grant_type", "refresh_token"},
        {"refresh_token", refresh_token_},
        {"scope", kScope}},
       true);
}
void MicrosoftAccount::send(Step step, const QUrl& url, const QJsonObject& json, bool form) {
  step_ = step;
  HttpRequest request;
  request.url = url;
  if (step == Step::Profile)
    request.headers["Authorization"] = "Bearer " + identity_.access_token.toUtf8();
  else {
    request.method = "POST";
    if (form) {
      QUrlQuery query;
      for (auto it = json.begin(); it != json.end(); ++it)
        query.addQueryItem(it.key(), it.value().toString());
      request.body = query.toString(QUrl::FullyEncoded).toUtf8();
      // QUrlQuery 保留加号；表单值中加号必须编码。
      request.body.replace("+", "%2B");
      request.headers["Content-Type"] = "application/x-www-form-urlencoded";
    } else {
      request.body = QJsonDocument(json).toJson(QJsonDocument::Compact);
      request.headers["Content-Type"] = "application/json";
    }
    request.headers["Accept"] = "application/json";
  }
  request_id_ = http_->request(request);
}
void MicrosoftAccount::poll() {
  if (QDateTime::currentDateTimeUtc() >= device_expires_) {
    fail(QCoreApplication::translate("Bugg", "授权码已过期，请重试"));
    return;
  }
  send(Step::Poll, QUrl(kAuthority + "token"),
       {{"client_id", client_id_},
        {"grant_type", "urn:ietf:params:oauth:grant-type:device_code"},
        {"device_code", device_code_}},
       true);
}
void MicrosoftAccount::received(const QByteArray& body, const QString& error, int status) {
  const auto data = QJsonDocument::fromJson(body).object();
  const auto code = data["error"].toString();
  if (step_ == Step::Poll && (code == "authorization_pending" || code == "slow_down")) {
    if (code == "slow_down") interval_ms_ += 5000;
    polling_.start(interval_ms_);
    return;
  }
  if (!error.isEmpty() || data.isEmpty() || !code.isEmpty()) {
    QString message = QCoreApplication::translate("Bugg", "登录请求失败，请重试");
    if (step_ == Step::Profile && status == 404)
      message = QCoreApplication::translate(
          "Bugg", "此微软账号没有 Minecraft Java 版游戏角色，请确认购买并创建角色");
    else if (step_ == Step::Refresh && code == "invalid_grant")
      message = QCoreApplication::translate("Bugg", "微软授权已过期，请重新登录");
    else if (step_ == Step::Xsts)
      message =
          QCoreApplication::translate("Bugg", "Xbox 授权失败，请检查 Xbox 资料、年龄及家庭设置");
    else if (code == "expired_token")
      message = QCoreApplication::translate("Bugg", "授权码已过期，请重试");
    else if (code == "authorization_declined" || code == "access_denied")
      message = QCoreApplication::translate("Bugg", "你已拒绝此次授权");
    else if (status)
      message += QString("（HTTP %1）").arg(status);
    else
      message = QCoreApplication::translate("Bugg", "无法连接登录服务，请检查网络后重试");
    fail(message);
    return;
  }
  if (step_ == Step::Device) {
    device_code_ = data["device_code"].toString();
    const auto code = data["user_code"].toString();
    if (device_code_.isEmpty() || code.isEmpty()) {
      fail(QCoreApplication::translate("Bugg", "微软未返回有效授权码"));
      return;
    }
    interval_ms_ = qMax(5, data["interval"].toInt(5)) * 1000;
    device_expires_ =
        QDateTime::currentDateTimeUtc().addSecs(qMin(1800, data["expires_in"].toInt(900)));
    emit authentication("waiting", code, {});
    polling_.start(interval_ms_);
  } else if (step_ == Step::Poll || step_ == Step::Refresh) {
    microsoft_token_ = data["access_token"].toString();
    if (microsoft_token_.isEmpty()) {
      fail(QCoreApplication::translate("Bugg", "微软未返回访问凭据"));
      return;
    }
    if (data.contains("refresh_token")) refresh_token_ = data["refresh_token"].toString();
    emit authentication("authorizing", {}, {});
    send(Step::Xbox, QUrl("https://user.auth.xboxlive.com/user/authenticate"),
         {{"Properties", QJsonObject{{"AuthMethod", "RPS"},
                                     {"SiteName", "user.auth.xboxlive.com"},
                                     {"RpsTicket", "d=" + microsoft_token_}}},
          {"RelyingParty", "http://auth.xboxlive.com"},
          {"TokenType", "JWT"}});
  } else if (step_ == Step::Xbox) {
    xbox_token_ = data["Token"].toString();
    const auto xui = data["DisplayClaims"].toObject()["xui"].toArray();
    user_hash_ = xui.isEmpty() ? QString() : xui[0].toObject()["uhs"].toString();
    if (xbox_token_.isEmpty() || user_hash_.isEmpty()) {
      fail(QCoreApplication::translate("Bugg", "Xbox 返回的身份无效"));
      return;
    }
    send(Step::Xsts, QUrl("https://xsts.auth.xboxlive.com/xsts/authorize"),
         {{"Properties",
           QJsonObject{{"SandboxId", "RETAIL"}, {"UserTokens", QJsonArray{xbox_token_}}}},
          {"RelyingParty", "rp://api.minecraftservices.com/"},
          {"TokenType", "JWT"}});
  } else if (step_ == Step::Xsts) {
    const auto token = data["Token"].toString();
    if (token.isEmpty()) {
      fail(QCoreApplication::translate("Bugg", "Xbox 安全令牌为空"));
      return;
    }
    const auto xui = data["DisplayClaims"].toObject()["xui"].toArray();
    if (!xui.isEmpty()) identity_.xuid = xui[0].toObject()["xid"].toString();
    send(Step::Minecraft, QUrl("https://api.minecraftservices.com/authentication/login_with_xbox"),
         {{"identityToken", "XBL3.0 x=" + user_hash_ + ';' + token}});
  } else if (step_ == Step::Minecraft) {
    identity_.access_token = data["access_token"].toString();
    expires_ = QDateTime::currentDateTimeUtc().addSecs(data["expires_in"].toInt(3600));
    if (identity_.access_token.isEmpty()) {
      fail(QCoreApplication::translate("Bugg", "Minecraft 访问凭据为空"));
      return;
    }
    send(Step::Profile, QUrl("https://api.minecraftservices.com/minecraft/profile"));
  } else if (step_ == Step::Profile) {
    identity_.name = data["name"].toString();
    identity_.uuid = data["id"].toString();
    identity_.kind = "microsoft";
    identity_.client_id = client_id_;
    if (identity_.name.isEmpty() ||
        !QRegularExpression("\\A[0-9a-fA-F]{32}\\z").match(identity_.uuid).hasMatch()) {
      fail(QCoreApplication::translate("Bugg", "Minecraft 游戏角色无效"));
      return;
    }
    microsoft_token_.clear();
    xbox_token_.clear();
    device_code_.clear();
    persist();
    emit authentication("idle", {}, {});
    emit profile_ready(identity_.name);
    const auto waiting = std::exchange(waiting_, {});
    for (auto id : waiting) emit credentials_ready(id, identity_, {});
    if (restoring_) {
      restoring_ = false;
      emit restored({});
    }
  }
}
void MicrosoftAccount::fail(const QString& error) {
  polling_.stop();
  device_code_.clear();
  identity_.access_token.clear();
  microsoft_token_.clear();
  xbox_token_.clear();
  emit authentication("failed", {}, error);
  const auto waiting = std::exchange(waiting_, {});
  for (auto id : waiting) emit credentials_ready(id, {}, error);
  if (restoring_) {
    restoring_ = false;
    emit restored(error);
  }
}
void MicrosoftAccount::persist() {
  storage_pending_ = true;
  if (storage_busy_) return;
  storage_busy_ = true;
  storage_pending_ = false;
  const auto payload = refresh_token_.isEmpty()
                           ? QByteArray()
                           : QJsonDocument(QJsonObject{{"refresh", refresh_token_},
                                                       {"name", identity_.name},
                                                       {"uuid", identity_.uuid}})
                                 .toJson(QJsonDocument::Compact);
  auto* watcher = new QFutureWatcher<QString>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
    const auto error = watcher->result();
    watcher->deleteLater();
    storage_busy_ = false;
    if (!error.isEmpty()) emit storage_error(error);
    if (storage_pending_) persist();
  });
  watcher->setFuture(QtConcurrent::run([path = path_, payload] {
    try {
      save_credentials(path, payload);
      return QString();
    } catch (const std::exception& error) {
      return QString::fromUtf8(error.what());
    }
  }));
}
void MicrosoftAccount::relocate_storage(const QString& path) { path_ = path; persist(); }
}  // namespace bugg
