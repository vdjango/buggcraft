#include "modules/multiplayer/application/multiplayer_service.h"

#include <QClipboard>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFutureWatcher>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QSysInfo>
#include <QThread>
#include <QUuid>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <cmath>
#include <future>
#include <thread>

#include "modules/account/infrastructure/credential_store.h"
#include "modules/room_sync/application/room_content_cache.h"
#include "platform/security/device_key.h"

static const bool control_resources_initialized = [] {
  Q_INIT_RESOURCE(bugg_control_trust);
  return true;
}();

namespace bugg {
namespace {
QString encode(const QByteArray& value) {
  return QString::fromLatin1(
      value.toBase64(QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals));
}
QJsonObject token_claims(const QJsonObject& profile) {
  const auto token = profile["token"].toString();
  if (!token.startsWith("acct1.")) return {};
  return QJsonDocument::fromJson(QByteArray::fromBase64(token.section('.', 1, 1).toLatin1(),
                                                        QByteArray::Base64UrlEncoding))
      .object();
}
QString response_error(const QJsonObject& result, const QString& error) {
  const auto detail = result["error"].toString();
  return detail.isEmpty() ? error : detail;
}
double measured_latency_ms(const QJsonValue& value) {
  const double number = value.toDouble(-1);
  return value.isDouble() && std::isfinite(number) && number >= 0 && number <= 1000000 ? number
                                                                                       : -1;
}
// LAN 状态的版本是展示文本（如 NeoForge 26.3），实例版本则是规范 ID。
bool world_version_matches(const QString& detected, const QString& expected) {
  if (expected.isEmpty()) return true;
  const QRegularExpression version("(?:^|[^A-Za-z0-9_.-])" + QRegularExpression::escape(expected) +
                                   "(?:$|[^A-Za-z0-9_.-])");
  return version.match(detected).hasMatch();
}
bool account_id(const QString& value) {
  static const QRegularExpression pattern("^[0-9a-f]{32}\\.[0-9a-f]{32}$");
  return pattern.match(value).hasMatch();
}
QString friend_code(const QString& account) {
  if (!account_id(account)) return {};
  const auto hash = QCryptographicHash::hash("buggcraft-friend-v1:" + account.toLatin1(),
                                             QCryptographicHash::Sha256);
  constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  QString code;
  for (int i = 0; i < 12; ++i) {
    if (i && i % 4 == 0) code += '-';
    unsigned index = 0;
    for (int bit = i * 5; bit < i * 5 + 5; ++bit)
      index = (index << 1) | ((static_cast<unsigned char>(hash[bit / 8]) >> (7 - bit % 8)) & 1);
    code += QLatin1Char(alphabet[index]);
  }
  return code;
}
}  // namespace
MultiplayerService::MultiplayerService(HttpClient* http, QString cache, QString engine,
                                       QObject* parent)
    : QObject(parent), http_(http), bridge_(std::move(engine)), cache_(std::move(cache)) {
  connect(&polling_, &QTimer::timeout, this, &MultiplayerService::poll);
  heartbeat_.setInterval(8000);
  connect(&heartbeat_, &QTimer::timeout, this, &MultiplayerService::heartbeat);
  room_poll_.setInterval(1000);
  connect(&room_poll_, &QTimer::timeout, this, &MultiplayerService::poll_room);
  announcement_.setInterval(1500);
  connect(&announcement_, &QTimer::timeout, this, &MultiplayerService::announce_room);
  preparation_timer_.setSingleShot(true);
  preparation_timer_.setInterval(500);
  connect(&preparation_timer_, &QTimer::timeout, this, &MultiplayerService::report_preparation);
  connect(&bridge_, &NativeBridge::drained, this, [this] {
    if (closing_ && !busy()) emit drained();
  });
  connect(&bridge_, &NativeBridge::disconnected, this, [this](const QString& error) {
    ++generation_;
    ++room_generation_;
    pending_room_.clear();
    pending_invites_.clear();
    ++lookup_generation_;
    heartbeat_.stop();
    room_poll_.stop();
    announcement_.stop();
    event_pending_ = false;
    message_ids_.clear();
    node_.clear();
    session_.clear();
    if (cache_cancelled_) cache_cancelled_->store(true);
    cache_key_.clear();
    preparation_timer_.stop();
    preparation_ = {};
    preparation_pending_ = false;
    room_probe_ = false;
    status_ = {{"state", "signedOut"}, {"error", error}};
    emit changed();
  });
  connect(http_, &HttpClient::response, this,
          [this](quint64 id, const QByteArray& bytes, const QString& error, int) {
            if (id == feedback_request_ && feedback_request_) {
              feedback_request_ = 0;
              const auto result = QJsonDocument::fromJson(bytes).object();
              auto detail = response_error(result, error);
              const bool accepted = detail.isEmpty() && result["accepted"].toBool() &&
                                    result["id"].toString() == feedback_id_;
              if (!accepted && detail.isEmpty()) detail = tr("反馈未确认，请稍后重试");
              feedback_ = {
                  {"busy", false}, {"id", accepted ? feedback_id_ : QString()}, {"error", detail}};
              emit changed();
              return;
            }
            if (id != request_ || !request_) return;
            request_ = 0;
            const auto callback = std::exchange(response_, {});
            const auto result = QJsonDocument::fromJson(bytes).object();
            // 协议错误也可能在 HTTP 200 中返回，不能把它当作仍在等待授权。
            const auto detail = response_error(result, error);
            if (callback)
              callback(result, result.isEmpty() && detail.isEmpty()
                                   ? QCoreApplication::translate("Bugg", "节点响应无效")
                                   : detail);
          });
}
void MultiplayerService::submit_feedback(const QString& message, const QString& contact,
                                         bool diagnostics) {
  if (closing_ || feedback_request_) return;
  const auto content = message.trimmed();
  const auto address = contact.trimmed();
  if (content.isEmpty() || content.toUtf8().size() > 8000 || address.toUtf8().size() > 320) {
    feedback_ = {{"error", tr("请填写问题描述，描述最多 8000 字节，联系方式最多 320 字节")}};
    emit changed();
    return;
  }
  if (feedback_id_.isEmpty() || feedback_message_ != content || feedback_contact_ != address ||
      feedback_diagnostics_ != diagnostics) {
    feedback_id_ = QUuid::createUuid().toString(QUuid::WithoutBraces);
    feedback_message_ = content;
    feedback_contact_ = address;
    feedback_diagnostics_ = diagnostics;
  }
  QJsonObject basic;
  if (diagnostics)
    basic = {{"application", "Bugg"},
             {"version", "C++ preview"},
             {"system", QSysInfo::productType()},
             {"architecture", QSysInfo::currentCpuArchitecture()}};
  HttpRequest request;
  request.url = QUrl(origin_ + "/v1/feedback/submit");
  request.method = "POST";
  request.body = QJsonDocument(QJsonObject{{"id", feedback_id_},
                                           {"message", content},
                                           {"contact", address},
                                           {"diagnostics", basic}})
                     .toJson(QJsonDocument::Compact);
  request.headers = {{"Content-Type", "application/json"}, {"Cache-Control", "no-store"}};
  request.blocked_redirect_hosts = {request.url.host()};
  request.maximum_bytes = 4096;
  request.total_ms = 15000;
  feedback_ = {{"busy", true}};
  feedback_request_ = http_->request(request);
  emit changed();
}
void MultiplayerService::report(const QString& error) {
  if (closing_) return;
  if (!renewing_ && !node_.isEmpty() &&
      (error.contains("account-device-inactive") || error.contains("token-expired") ||
       error.contains("account-token-expired") || error.contains("grant-revoked"))) {
    expire_authorization(error);
    return;
  }
  status_["error"] = error.left(300);
  emit changed();
}
void MultiplayerService::post(const QString& path, const QJsonObject& body,
                              std::function<void(const QJsonObject&, const QString&)> complete) {
  if (closing_ || request_) return;
  HttpRequest request;
  request.url = QUrl(origin_ + path);
  if (origin_ == "https://81.70.85.232") {
    QFile certificate(":/bugg/assets/control/beijing-test-ca.pem");
    if (certificate.open(QIODevice::ReadOnly)) request.ca_pem = certificate.readAll();
  }
  request.method = "POST";
  request.body = QJsonDocument(body).toJson(QJsonDocument::Compact);
  request.headers = {{"Content-Type", "application/json"}, {"Cache-Control", "no-store"}};
  request.maximum_bytes = 65536;
  request.total_ms = 15000;
  // 凭据请求绝不跨 origin 跳转，包括同站名升级/重定向。
  request.blocked_redirect_hosts = {request.url.host()};
  const auto generation = generation_;
  response_ = [this, generation, complete = std::move(complete)](const QJsonObject& result,
                                                                 const QString& error) {
    if (!closing_ && generation == generation_) complete(result, error);
  };
  request_ = http_->request(request);
}
QVariantMap MultiplayerService::status() const {
  auto result = status_;
  result["authorized"] = !profile_.isEmpty() && token_claims(profile_)["e"].toDouble() >
                                                    QDateTime::currentSecsSinceEpoch();
  return result;
}
void MultiplayerService::login(const QString& origin) {
  // 等待授权时再次点击只重开原链接，不创建第二份设备申请。
  if (!closing_ && status_.value("state") == "authorizing") {
    const auto verification = status_.value("verificationUrl").toUrl();
    if (verification.isValid() && !verification.isEmpty()) QDesktopServices::openUrl(verification);
    return;
  }
  if (closing_ || request_ || status_.value("state") == "connecting" || !node_.isEmpty()) return;
  QUrl url(origin.trimmed().isEmpty() ? default_origin() : origin.trimmed());
  if (url.scheme() != "https" || url.host().isEmpty() || !url.userInfo().isEmpty() ||
      url.hasQuery() || url.hasFragment() || (!url.path().isEmpty() && url.path() != "/")) {
    report(QCoreApplication::translate("Bugg", "请输入可信节点的 HTTPS 网址"));
    return;
  }
  const auto selected_origin = url.adjusted(QUrl::RemovePath).toString();
  if (selected_origin == origin_ && !profile_.isEmpty() &&
      token_claims(profile_)["e"].toDouble() > QDateTime::currentSecsSinceEpoch()) {
    status_.remove("error");
    connect_profile();
    return;
  }
  origin_ = selected_origin;
  try {
    key_ = create_device_key();
  } catch (const std::exception& error) {
    report(QString::fromUtf8(error.what()));
    return;
  }
  const auto generation = ++generation_;
  status_ = {{"state", "authorizing"}};
  emit changed();
  post("/api/launcher/start",
       {{"key", device_public_key(key_)},
        {"name", QSysInfo::machineHostName().left(64)},
        {"remember", true}},
       [this, generation](const QJsonObject& result, const QString& error) {
         if (generation != generation_ || closing_) return;
         device_id_ = result["id"].toString();
         nonce_ = result["nonce"].toString();
         const auto verification = result["verification_uri"].toString();
         if (!error.isEmpty() || device_id_.isEmpty() || nonce_.isEmpty() ||
             verification != origin_ + "/account/access?launcher=" + device_id_) {
           status_["state"] = "signedOut";
           report(error.isEmpty() ? QCoreApplication::translate("Bugg", "节点登录网址不匹配")
                                  : error);
           return;
         }
         deadline_ = QDateTime::currentDateTimeUtc().addSecs(
             qBound(1, result["expires_in"].toInt(600), 600));
         status_["verificationUrl"] = verification;
         QDesktopServices::openUrl(QUrl(verification));
         polling_.start(qBound(1, result["interval"].toInt(3), 30) * 1000);
         emit changed();
       });
}
void MultiplayerService::poll() {
  if (closing_ || request_) return;
  if (QDateTime::currentDateTimeUtc() >= deadline_) {
    polling_.stop();
    status_["state"] = "signedOut";
    report(QCoreApplication::translate("Bugg", "登录已过期，请重试"));
    return;
  }
  try {
    const auto signature = sign_device_message(
        key_, {{"p", "buggcraft-launcher-poll-v1"}, {"id", device_id_}, {"nonce", nonce_}});
    post("/api/launcher/poll", {{"id", device_id_}, {"signature", signature}},
         [this](const QJsonObject& result, const QString& error) {
           const auto state = result["status"].toString();
           const auto detail = !error.isEmpty() ? error
                               : state == "pending" || state == "approved"
                                   ? QString()
                                   : QCoreApplication::translate("Bugg", "节点响应无效");
           if (!detail.isEmpty()) {
             polling_.stop();
             status_["state"] = "signedOut";
             report(detail);
             return;
           }
           if (state == "approved") {
             polling_.stop();
             approved(result);
           }
         });
  } catch (const std::exception& error) {
    polling_.stop();
    status_["state"] = "signedOut";
    report(QString::fromUtf8(error.what()));
  }
}
void MultiplayerService::approved(const QJsonObject& result) {
  auto profile = result["profile"].toObject();
  const auto grant = token_claims(profile)["g"].toObject();
  if (profile["server_host"].toString().isEmpty() ||
      profile["server_public_key"].toString().isEmpty() ||
      !profile["token"].toString().startsWith("acct1.") || grant["r"].toString() != device_id_ ||
      grant["d"].toObject() != device_public_key(key_)) {
    expire_authorization(QCoreApplication::translate("Bugg", "节点授权与此设备不匹配"));
    return;
  }
  profile["token"] = profile["token"].toString().section('~', 0, 0) + '~' + encode(key_.right(32));
  profile_ = profile;
  status_["name"] = result["name"].toString();
  persist();
  connect_profile();
}
void MultiplayerService::connect_profile() {
  if (closing_ || profile_.isEmpty()) return;
  const auto generation = generation_;
  const bool connected = !node_.isEmpty();
  if (!connected) status_["state"] = "connecting";
  emit changed();
  QJsonObject connection{{"selection", "latency"}};
  if (profile_.contains("control"))
    connection["profile"] = profile_;
  else
    connection["code"] =
        "buggnode1-" + encode(QJsonDocument(profile_).toJson(QJsonDocument::Compact));
  bridge_.call("node.add", connection,
               [this, generation, connected](const QJsonObject& result, const QString& error) {
                 if (closing_ || generation != generation_) return;
                 const auto detail = response_error(result, error);
                 const auto previous = node_;
                 if (!result["node"].toString().isEmpty() || !connected)
                   node_ = result["node"].toString();
                 if (!previous.isEmpty() && previous != node_) {
                   // A renewed handle can overtake unsent telemetry for the old handle.
                   status_["loading"] = false;
                   status_["nodesBusy"] = false;
                   status_.remove("routes");
                   status_.remove("nodesError");
                   if (session_.isEmpty())
                     bridge_.call("node.remove", {{"node", previous}},
                                  [](const auto&, const auto&) {});
                   else
                     retired_nodes_.append(previous);
                 }
                 status_["state"] = node_.isEmpty() ? "signedOut" : "ready";
                 status_["nodeName"] = result["name"].toString();
                 status_["error"] = detail.contains("No managed node is ready") ||
                                            detail.contains("No reachable managed node")
                                        ? tr("账号已授权，暂时没有可用的联机节点，请重试连接。")
                                        : detail;
                 emit changed();
                 if (!node_.isEmpty()) {
                   refresh();
                   heartbeat_.start();
                   heartbeat();
                 }
               });
}
void MultiplayerService::restore() {
  if (restoring_ || closing_ || request_ || !node_.isEmpty() ||
      status_.value("state") != "signedOut")
    return;
  restoring_ = true;
  const auto generation = generation_;
  auto* watcher = new QFutureWatcher<QPair<QJsonObject, QString>>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher, generation] {
    const auto [saved, error] = watcher->result();
    watcher->deleteLater();
    restoring_ = false;
    if (closing_) {
      if (!busy()) emit drained();
      return;
    }
    if (generation == generation_ && !saved.isEmpty()) {
      key_ = QByteArray::fromBase64(saved["key"].toString().toLatin1());
      profile_ = saved["profile"].toObject();
      device_id_ = saved["device"].toString();
      origin_ = saved["origin"].toString(default_origin());
      if (origin_ == "https://81.70.85.232") origin_ = default_origin();
      if (key_.size() == 96 &&
          token_claims(profile_)["g"].toObject()["d"].toObject() == device_public_key(key_))
        renew_profile();
      else
        profile_ = {};
    }
    emit restored(error);
    if (!error.isEmpty()) report(error);
  });
  watcher->setFuture(QtConcurrent::run([path = cache_ + "/node-credentials.bin"] {
    try {
      return qMakePair(QJsonDocument::fromJson(load_credentials(path)).object(), QString());
    } catch (const std::exception& error) {
      return qMakePair(QJsonObject(), QString::fromUtf8(error.what()));
    }
  }));
}
void MultiplayerService::persist() {
  storage_pending_ = true;
  if (storage_busy_) return;
  storage_pending_ = false;
  storage_busy_ = true;
  const auto payload =
      profile_.isEmpty() ? QByteArray()
                         : QJsonDocument(QJsonObject{{"key", QString::fromLatin1(key_.toBase64())},
                                                     {"profile", profile_},
                                                     {"device", device_id_},
                                                     {"origin", origin_}})
                               .toJson(QJsonDocument::Compact);
  auto* watcher = new QFutureWatcher<QString>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
    const auto error = watcher->result();
    watcher->deleteLater();
    storage_busy_ = false;
    if (!error.isEmpty()) report(error);
    if (storage_pending_) persist();
    if (closing_ && !busy()) emit drained();
  });
  watcher->setFuture(QtConcurrent::run([path = cache_ + "/node-credentials.bin", payload] {
    try {
      save_credentials(path, payload);
      return QString();
    } catch (const std::exception& error) {
      return QString::fromUtf8(error.what());
    }
  }));
}
void MultiplayerService::renew_profile() {
  if (closing_ || renewing_ || request_ || profile_.isEmpty()) return;
  renewing_ = true;
  const auto claims = token_claims(profile_);
  const auto failed = [this, claims](const QString& error) {
    renewing_ = false;
    renewal_retry_ = QDateTime::currentDateTimeUtc().addSecs(60);
    if (claims["e"].toInteger() <= QDateTime::currentSecsSinceEpoch() ||
        error.contains("revoked") || error.contains("inactive") || error.contains("not-found")) {
      expire_authorization(QCoreApplication::translate("Bugg", "节点授权已失效，请重新登录"));
    } else if (node_.isEmpty())
      connect_profile();
    else
      report(error);
  };
  post("/api/launcher/challenge", {{"id", device_id_}},
       [this, claims, failed](const QJsonObject& challenge, const QString& detail) {
         const auto message = challenge["message"].toObject();
         if (!detail.isEmpty()) {
           failed(detail);
           return;
         }
         if (message["p"] != "buggcraft-launcher-refresh-v1" || message["id"] != device_id_ ||
             message["i"] != claims["g"].toObject()["i"] || message["o"] != origin_) {
           renewing_ = false;
           expire_authorization(QCoreApplication::translate("Bugg", "节点身份已变更，请重新登录"));
           return;
         }
         try {
           post(
               "/api/launcher/refresh",
               {{"nonce", message["nonce"]}, {"signature", sign_device_message(key_, message)}},
               [this, failed](const QJsonObject& value, const QString& error) {
                 if (!error.isEmpty()) {
                   failed(error);
                   return;
                 }
                 renewing_ = false;
                 const auto updated = value["profile"].toObject();
                 if (updated["server_public_key"] != profile_["server_public_key"] ||
                     token_claims(updated)["e"].toInteger() <= QDateTime::currentSecsSinceEpoch()) {
                   expire_authorization(
                       QCoreApplication::translate("Bugg", "节点身份已变更，请重新登录"));
                   return;
                 }
                 renewal_retry_ = QDateTime::currentDateTimeUtc().addSecs(60);
                 approved(value);
               });
         } catch (const std::exception& error) {
           failed(QString::fromUtf8(error.what()));
         }
       });
}
void MultiplayerService::expire_authorization(const QString& error) {
  logout();
  status_["authorizationExpired"] = true;
  report(error);
}
void MultiplayerService::poll_room() {
  if (closing_ || session_.isEmpty() || event_pending_) return;
  event_pending_ = true;
  const auto generation = room_generation_;
  bridge_.call("chat.poll", {{"session", session_}},
               [this, generation](const QJsonObject& value, const QString& error) {
                 if (closing_ || generation != room_generation_) return;
                 event_pending_ = false;
                 if (!error.isEmpty()) {
                   status_["chatError"] = error;
                   emit changed();
                   return;
                 }
                 apply_room_events(value["events"].toArray());
               });
}
void MultiplayerService::apply_room_events(const QJsonArray& events) {
  if (events.isEmpty()) return;
  auto messages = status_.value("messages").toList();
  auto room = status_.value("room").toMap();
  for (const auto& entry : events) {
    const auto event = entry.toObject();
    const auto type = event["type"].toString();
    if (type == "message") {
      const auto id = QString::fromLatin1(
          QCryptographicHash::hash(QJsonDocument(event).toJson(QJsonDocument::Compact),
                                   QCryptographicHash::Sha256)
              .toHex());
      // 重连重放不重复插入；不使用本地乐观消息冒充服务器确认。
      const auto key = event.contains("id") ? event["id"].toVariant().toString() : id;
      if (message_ids_.contains(key)) continue;
      message_ids_.insert(key);
      messages.append(QVariantMap{{"id", key},
                                  {"sender", event["sender"].toString()},
                                  {"text", event["text"].toString()},
                                  {"time", event["time"].toVariant()}});
      while (messages.size() > 200) {
        message_ids_.remove(messages.first().toMap().value("id").toString());
        messages.removeFirst();
      }
      status_.remove("chatError");
    } else if (type == "members" && event["snapshot"].isObject()) {
      status_["room"] = room;
      room_result({{"session", session_}, {"info", QJsonObject{{"lobby", event["snapshot"]}}}}, {});
      room = status_.value("room").toMap();
    } else if (type == "room") {
      room["availability"] = event["state"] == "ready" ? "ready" : "waiting";
      room["reason"] = event["reason"].toString();
    } else if (type == "latency" && room.value("role") != "host") {
      room["latencyMs"] = measured_latency_ms(event["latency_ms"]);
    } else if (type == "node-latency") {
      room["nodeLatencyMs"] = measured_latency_ms(event["latency_ms"]);
    } else if (type == "bridge" && event["node"].isString()) {
      room["nodeName"] = event["node"].toString();
      room["nodeLatencyMs"] = -1;
      if (room.value("role") != "host") room["latencyMs"] = -1;
    } else if (type == "transport" && room.value("role") != "host") {
      room["connectionMode"] = event["transport"].toString();
    } else if (type == "offline")
      status_["chatError"] = event["error"].toString();
    else if (type == "ready")
      status_.remove("chatError");
  }
  status_["room"] = room;
  status_["messages"] = messages;
  emit changed();
}
void MultiplayerService::send_chat(const QString& input) {
  const auto text = input.trimmed();
  if (closing_ || session_.isEmpty() || status_.value("chatBusy").toBool()) return;
  if (text.isEmpty() || text.size() > 256 ||
      text.contains(QRegularExpression("[\\x00-\\x1f\\x7f\\x{00a7}]"))) {
    status_["chatError"] = QCoreApplication::translate("Bugg", "消息为空或过长");
    emit changed();
    return;
  }
  const auto generation = room_generation_;
  status_["chatBusy"] = true;
  status_.remove("chatError");
  emit changed();
  bridge_.call("chat.send", {{"session", session_}, {"text", text}},
               [this, generation](const QJsonObject& value, const QString& error) {
                 if (closing_ || generation != room_generation_) return;
                 status_["chatBusy"] = false;
                 status_["chatError"] = response_error(value, error);
                 if (status_.value("chatError").toString().isEmpty()) emit chat_sent();
                 poll_room();
                 emit changed();
               });
}
void MultiplayerService::announce_room() {
  const auto room = status_.value("room").toMap();
  if (closing_ || session_.isEmpty() || room.value("role") == "host" ||
      room.value("availability") != "ready" || room.value("state") != "online")
    return;
  const auto port = room.value("address").toString().section(':', -1).toInt();
  if (port < 1 || port > 65535) return;
  const auto plain = QStringLiteral("【BUGG联机】") + room.value("title").toString();
  const QString colors = "cb6eab9d";
  QString title;
  int index = announcement_frame_++;
  // 每四字换色，避免一字一色超过 LAN 的短标题预算。
  for (int i = 0; i < qMin<qsizetype>(32, plain.size()); ++i) {
    if (i % 4 == 0) title += QChar(0x00a7) + QString(colors[index++ % colors.size()]);
    const auto character = plain[i];
    if (character.unicode() >= 32 && character != QChar(0x00a7)) title += character;
  }
  title += QChar(0x00a7) + QStringLiteral("r");
  bridge_.call("game.announce", {{"port", port}, {"title", title}},
               [](const auto&, const auto&) {});
}
void MultiplayerService::select_room_instance(const QString& instance_id) {
  auto room = status_.value("room").toMap();
  if (closing_ || session_.isEmpty() || room.value("role") == "host") return;
  if (QStringList{"preparing", "running", "stopping"}.contains(
          launch_status_.value("state").toString()))
    return;
  const auto revision = ++content_revision_;
  room.remove("instanceId");
  room.remove("syncName");
  room.remove("syncState");
  room["candidateId"] = instance_id;
  room["checking"] = !instance_id.isEmpty();
  room["compatibility"] = QCoreApplication::translate("Bugg", "请选择本地游戏或安装房间配置");
  room["canSupplement"] = false;
  room.remove("loaderWarning");
  status_["room"] = room;
  emit changed();
  if (!instance_id.isEmpty())
    emit instance_check_requested(session_, revision, instance_id, room.value("game").toMap());
}
void MultiplayerService::content_checked(const QString& session, quint64 revision,
                                         const QString& instance_id, const QVariantMap& result) {
  if (closing_ || session != session_ || revision != content_revision_) return;
  auto room = status_.value("room").toMap();
  room["checking"] = false;
  room["compatibility"] = result.value("error", result.value("detail"));
  room["canSupplement"] = result.value("canSupplement", false);
  room["loaderWarning"] = result.value("warning");
  if (result.value("compatible").toBool()) room["instanceId"] = instance_id;
  status_["room"] = room;
  emit changed();
  preparation_progress(session_, {}, result.value("compatible").toBool() ? "ready" : "idle", -1);
}
void MultiplayerService::launch_room() {
  const auto room = status_.value("room").toMap();
  if (closing_ || session_.isEmpty()) return;
  if (room.value("instanceId").toString().isEmpty() || room.value("checking").toBool() ||
      QStringList{"queued", "running", "cancelling"}.contains(room.value("syncState").toString())) {
    emit preparation_required();
    return;
  }
  QVariantMap contributions{{"roomGame", room.value("game")}, {"roomSession", session_}};
  if (room.value("role") == "host")
    contributions["hostPlayerCount"] = room.value("memberCount", 1);
  else if (room.value("availability") == "ready") {
    contributions["server"] = room.value("address");
    contributions["lanServer"] = true;
  }
  emit launch_requested(room.value("instanceId").toString(), contributions);
}
void MultiplayerService::sync_room(const QString& mode) {
  const auto room = status_.value("room").toMap();
  if (closing_ || session_.isEmpty() || room.value("role") == "host") return;
  if (mode != "fresh" && mode != "existing") return;
  if (QStringList{"queued", "running", "cancelling"}.contains(room.value("syncState").toString()))
    return;
  if (mode == "existing" &&
      (!room.value("canSupplement").toBool() || room.value("checking").toBool()))
    return;
  const auto game = room.value("game").toMap();
  if (game.value("version").toString().isEmpty()) {
    report(QCoreApplication::translate("Bugg", "房间尚未提供游戏版本"));
    return;
  }
  const auto fingerprint = QString::fromLatin1(
      QCryptographicHash::hash(
          QJsonDocument(QJsonObject::fromVariantMap(game)).toJson(QJsonDocument::Compact),
          QCryptographicHash::Sha256)
          .toHex()
          .left(8));
  const auto base = mode == "existing" ? room.value("candidateId").toString() : QString();
  const auto suffix = base.isEmpty()
                          ? QString()
                          : '-' + QString::fromLatin1(QCryptographicHash::hash(
                                                          base.toUtf8(), QCryptographicHash::Sha256)
                                                          .toHex()
                                                          .left(8));
  const auto name = game.value("version").toString() + '-' +
                    game.value("loader", "vanilla").toString() + '-' +
                    game.value("loader_version").toString() + "-BUGG-" +
                    room.value("id").toString().left(8) + '-' + fingerprint + suffix;
  auto current = room;
  current["syncName"] = name;
  current["syncState"] = "queued";
  current.remove("instanceId");
  ++content_revision_;
  status_["room"] = current;
  emit changed();
  emit sync_requested({{"kind", "room"},
                       {"name", name},
                       {"roomSession", session_},
                       {"roomGame", game},
                       {"roomConfig", room.value("lobby").toMap().value("config_id")},
                       {"baseInstance", base},
                       {"game", game.value("version")},
                       {"loader", game.value("loader", "vanilla").toString().toLower()},
                       {"loaderVersion", game.value("loader_version")}});
}
void MultiplayerService::content_ready(const QString& session, const QString& instance_id,
                                       const QString& config) {
  if (closing_ || session != session_ || session_.isEmpty()) return;
  auto room = status_.value("room").toMap();
  if (room.value("lobby").toMap().value("config_id").toString() != config) return;
  room["instanceId"] = instance_id;
  room["candidateId"] = instance_id;
  room["syncState"] = "ready";
  room["compatibility"] = QString();
  room["checking"] = false;
  room["canSupplement"] = true;
  status_["room"] = room;
  emit changed();
  preparation_progress(session, {}, "ready", 1);
}
QJsonObject MultiplayerService::content_request(const QString& method, QJsonObject parameters,
                                                const Cancellation& cancelled) {
  // 仅安装工作线程使用；该端口不对 QML 暴露任意 RPC。
  if (QThread::currentThread() == thread())
    throw std::logic_error("Room content requests require a worker thread");
  if (!QStringList{"mods.manifest", "mods.fetch", "mods.status", "mods.cancel"}.contains(method) &&
      !(method == "room.request" &&
        parameters["request"].toObject()["op"] == "content_cache_grant"))
    throw std::runtime_error("Unsupported room content operation");
  auto promise = std::make_shared<std::promise<QPair<QJsonObject, QString>>>();
  auto future = promise->get_future();
  QMetaObject::invokeMethod(
      this,
      [this, method, parameters, cancelled, promise] {
        if (closing_ || cancelled->load() || session_.isEmpty() ||
            parameters["session"] != session_) {
          promise->set_value({{}, "Room session ended"});
          return;
        }
        const auto generation = room_generation_;
        bridge_.call(method, parameters,
                     [this, generation, promise, cancelled, parameters](const auto& value,
                                                                        const auto& error) {
                       if (cancelled->load() && !value["transfer"].toString().isEmpty() &&
                           !closing_ && generation == room_generation_)
                         bridge_.call(
                             "mods.cancel",
                             {{"session", parameters["session"]}, {"transfer", value["transfer"]}},
                             [](const auto&, const auto&) {});
                       promise->set_value({value, closing_ || generation != room_generation_
                                                      ? "Room session ended"
                                                      : response_error(value, error)});
                     });
      },
      Qt::QueuedConnection);
  while (future.wait_for(std::chrono::milliseconds(50)) != std::future_status::ready)
    check_cancelled(cancelled);
  check_cancelled(cancelled);
  const auto [value, error] = future.get();
  if (!error.isEmpty()) throw std::runtime_error(error.toStdString());
  return value;
}
void MultiplayerService::relocate_storage(const QString& cache) {
  cache_ = cache;
  persist();
}
void MultiplayerService::logout() {
  ++generation_;
  renewing_ = false;
  polling_.stop();
  heartbeat_.stop();
  if (request_) http_->cancel(std::exchange(request_, 0));
  response_ = {};
  leave_room();
  if (!node_.isEmpty())
    bridge_.call("node.remove", {{"node", node_}}, [](const auto&, const auto&) {});
  node_.clear();
  profile_ = {};
  cancel_lookup();
  ignored_invites_.clear();
  key_.fill('\0');
  key_.clear();
  status_ = {{"state", "signedOut"}, {"rooms", QVariantList{}}, {"friends", QVariantList{}}};
  persist();
  emit changed();
}
void MultiplayerService::refresh_nodes() { node_routes("node.routes", {{"refresh", true}}); }
void MultiplayerService::select_node(int index) {
  if (index < -1) return;
  node_routes(index < 0 ? "node.routes" : "node.select",
              index < 0 ? QJsonObject{{"auto", true}} : QJsonObject{{"index", index}});
}
void MultiplayerService::node_routes(const QString& method, const QJsonObject& parameters) {
  if (closing_ || node_.isEmpty() || status_.value("nodesBusy").toBool()) return;
  status_["nodesBusy"] = true;
  status_.remove("nodesError");
  emit changed();
  auto request = parameters;
  request["node"] = node_;
  const auto generation = generation_;
  const auto node = node_;
  bridge_.call(method, request,
               [this, generation, node](const QJsonObject& value, const QString& error) {
                 if (closing_ || generation != generation_ || node != node_) return;
                 status_["nodesBusy"] = false;
                 const auto detail = response_error(value, error);
                 status_["nodesError"] = detail;
                 if (detail.isEmpty()) {
                   status_["routes"] = value["routes"].toArray().toVariantList();
                   status_["autoNode"] = value["auto"].toBool(false);
                   status_["nodeName"] = value["name"].toString();
                   status_["latency"] = value["node_latency_ms"].toDouble(-1);
                 }
                 emit changed();
               });
}
void MultiplayerService::refresh(const QString& query, bool background) {
  if (closing_ || node_.isEmpty() || status_.value("loading").toBool()) return;
  room_query_ = query.left(100);
  const auto generation = generation_;
  const auto node = node_;
  const auto priority =
      background ? NativeBridge::Priority::Background : NativeBridge::Priority::Interactive;
  status_["loading"] = true;
  emit changed();
  bridge_.call(
      "room.list", {{"node", node_}, {"query", room_query_}, {"limit", 50}},
      [this, generation, node](const QJsonObject& value, const QString& error) {
        if (closing_ || generation != generation_ || node != node_) return;
        status_["loading"] = false;
        const auto detail = response_error(value, error);
        if (detail.isEmpty()) {
          status_["rooms"] = value["rooms"].toArray().toVariantList();
          status_["latency"] = value["node_latency_ms"].toDouble(-1);
          status_["nodeName"] = value["node_name"].toString();
        }
        report(detail);
      },
      priority);
  bridge_.call(
      "node.request", {{"node", node_}, {"request", QJsonObject{{"op", "social"}}}},
      [this, generation, node](const QJsonObject& value, const QString& error) {
        if (closing_ || generation != generation_ || node != node_) return;
        const auto detail = response_error(value, error);
        if (detail.isEmpty()) {
          apply_social(value);
        } else
          report(detail);
      },
      priority);
}
void MultiplayerService::heartbeat() {
  if (closing_ || node_.isEmpty()) return;
  if (!renewing_ && !request_ && QDateTime::currentDateTimeUtc() >= renewal_retry_ &&
      token_claims(profile_)["e"].toInteger() <= QDateTime::currentSecsSinceEpoch() + 300) {
    renew_profile();
    return;
  }
  const auto generation = generation_;
  const auto node = node_;
  const auto room = status_.value("room").toMap();
  QJsonObject presence;
  if (!room.value("id").toString().isEmpty() && !room.value("title").toString().isEmpty())
    presence = {{"room", room.value("id").toString()},
                {"room_role", room.value("role").toString()},
                {"room_title", room.value("title").toString()},
                {"room_state", room.value("availability").toString()}};
  bridge_.call(
      "social.operate", {{"node", node_}, {"operation", "presence"}, {"fields", presence}},
      [this, generation, node](const QJsonObject& value, const QString& error) {
        if (closing_ || generation != generation_ || node != node_) return;
        if (!response_error(value, error).isEmpty()) report(response_error(value, error));
      },
      NativeBridge::Priority::Background);
  refresh(room_query_, true);
  const auto session = session_;
  if (!session.isEmpty())
    bridge_.call(
        "session.list", {},
        [this, generation, session](const QJsonObject& value, const QString& error) {
          if (closing_ || generation != generation_ || session != session_) return;
          if (!error.isEmpty())
            report(error);
          else
            for (const auto& entry : value["sessions"].toArray()) {
              const auto current = entry.toObject();
              if (current["session"] != session) continue;
              room_result(current, {});
              const auto room = status_.value("room").toMap();
              if (room.value("role") != "host" || room.value("availability") == "ready" ||
                  room_probe_)
                break;
              discover_worlds();
              break;
            }
        },
        NativeBridge::Priority::Background);
}
void MultiplayerService::room_result(const QJsonObject& value, const QString& error) {
  status_["roomBusy"] = false;
  if (!response_error(value, error).isEmpty()) {
    report(response_error(value, error));
    return;
  }
  if (value["session"].toString().isEmpty()) {
    report(QCoreApplication::translate("Bugg", "房间响应无效，请重试"));
    return;
  }
  if (value["state"].toString() == "stopped") {
    const auto reason = value["reason"].toString();
    leave_room();
    report(reason.isEmpty() ? QCoreApplication::translate("Bugg", "房间连接已结束") : reason);
    return;
  }
  const bool created = session_ != value["session"].toString();
  session_ = value["session"].toString();
  auto room = created ? pending_room_ : status_.value("room").toMap();
  pending_room_.clear();
  const auto info = value["info"].toObject();
  // 只发布用户操作所需的邀请/本机端口，不发布节点 profile 或其他凭据。
  room["session"] = session_;
  for (const auto* field : {"role", "address", "transport", "state", "reason"})
    if (value.contains(field)) room[field] = value[field].toVariant();
  if (value.contains("room")) room["id"] = value["room"].toString();
  if (info.contains("title")) room["title"] = info["title"].toString();
  if (info.contains("node_name")) room["nodeName"] = info["node_name"].toString();
  if (value.contains("node_name")) room["nodeName"] = value["node_name"].toString();
  if (info.contains("availability"))
    room["availability"] = info["availability"] == "ready" ? "ready" : "waiting";
  if (info.contains("game")) room["game"] = info["game"].toObject().toVariantMap();
  // configure/retarget 的元数据快照可能暂不含成员；同一会话保留上次成员快照，
  // 不能将省略字段当作撤销管理权。显式 lobby 仍完整替换，权限最终由节点检查。
  const auto lobby = info.contains("lobby")
                         ? info["lobby"].toObject()
                         : QJsonObject::fromVariantMap(room.value("lobby").toMap());
  const bool configuration_changed =
      !created && !room.value("lobby").toMap().value("config_id").toString().isEmpty() &&
      room.value("lobby").toMap().value("config_id").toString() != lobby["config_id"].toString();
  if (configuration_changed && room.value("role") != "host") {
    ++content_revision_;
    emit content_invalidated(session_);
    room.remove("instanceId");
    room.remove("syncName");
    room.remove("syncState");
    room["checking"] = false;
    room["canSupplement"] = false;
    room["compatibility"] = QCoreApplication::translate("Bugg", "房间配置已改变，请重新同步");
  }
  room["lobby"] = lobby.toVariantMap();
  room["isManager"] =
      !lobby["self_id"].toString().isEmpty() && lobby["self_id"] == lobby["manager_id"];
  room["isProvider"] =
      !lobby["self_id"].toString().isEmpty() && lobby["self_id"] == lobby["provider_id"];
  if (info.contains("public")) room["public"] = info["public"].toBool();
  if (info.contains("require_invite")) room["requireInvite"] = info["require_invite"].toBool();
  if (info.contains("allow_mod_transfer"))
    room["allowSharing"] = info["allow_mod_transfer"].toBool();
  QVariantList members;
  double self_node_latency = -1;
  double self_host_latency = -1;
  bool self_has_node_latency = false;
  bool self_has_host_latency = false;
  for (const auto& entry : lobby["members"].toArray()) {
    const auto member = entry.toObject();
    QVariantMap item;
    for (const auto* field : {"id", "name", "account_name", "state", "stage", "path", "online",
                              "rtt_ms", "rtt_kind", "done", "total", "host_rtt_method", "stale"})
      item[field] = member[field].toVariant();
    for (const auto* field : {"node_rtt_ms", "host_rtt_ms"}) {
      const bool node = qstrcmp(field, "node_rtt_ms") == 0;
      const auto kind = node ? "node" : "game";
      const auto latency = measured_latency_ms(member.contains(field)       ? member[field]
                                               : member["rtt_kind"] == kind ? member["rtt_ms"]
                                                                            : QJsonValue{});
      const auto result = latency >= 0 && !member["stale"].toBool() && member["online"].toBool(true)
                              ? latency
                              : -1.0;
      item[field] = result;
      if (member["id"] == lobby["self_id"] && !member["id"].toString().isEmpty()) {
        if (node) {
          self_node_latency = result;
          self_has_node_latency = member.contains(field) || member["rtt_kind"] == kind ||
                                  member["stale"].toBool() || !member["online"].toBool(true);
        } else {
          self_host_latency = result;
          self_has_host_latency = member.contains(field) || member["rtt_kind"] == kind ||
                                  member["stale"].toBool() || !member["online"].toBool(true);
        }
      }
    }
    members.append(item);
  }
  room["members"] = members;
  int online = 0;
  double latency = room.value("latencyMs", -1).toDouble();
  QString mode = room.value("role") == "host" ? "local" : room.value("transport").toString();
  for (const auto& item : members) {
    const auto member = item.toMap();
    if (member.value("online", true).toBool()) ++online;
    if (member.value("id") == lobby["self_id"].toVariant() && room.value("role") != "host") {
      const auto path = member.value("path").toString();
      if (path == "p2p" || path == "relay") mode = path;
    }
  }
  room["memberCount"] = online;
  room["connectionMode"] = mode;
  if (self_has_node_latency) room["nodeLatencyMs"] = self_node_latency;
  if (room.value("role") == "host")
    room["latencyMs"] = 0;
  else if (self_has_host_latency)
    room["latencyMs"] = self_host_latency;
  else
    room["latencyMs"] = latency;
  if (value.contains("invite")) room["invite"] = value["invite"].toString();
  status_["room"] = room;
  emit changed();
  update_acceleration();
  dispatch_invites();
  if (created) {
    status_["messages"] = QVariantList{};
    message_ids_.clear();
    event_pending_ = false;
    room_poll_.start();
    if (room.value("role") != "host") announcement_.start();
    emit room_joined();
    refresh(room_query_);
    heartbeat();
  }
}
void MultiplayerService::complete_room(quint64 operation, const QJsonObject& value,
                                       const QString& error) {
  if (closing_ || operation != room_generation_) {
    const auto session = value["session"].toString();
    if (!closing_ && !session.isEmpty())
      bridge_.call("room.close", {{"session", session}}, [](const auto&, const auto&) {});
    return;
  }
  room_result(value, error);
  pending_room_.clear();
}
void MultiplayerService::create_room(const QString& title, const QString& directory,
                                     const QString& player, const QVariantMap& options) {
  if (closing_ || node_.isEmpty() || !session_.isEmpty() || status_.value("roomBusy").toBool())
    return;
  const auto game = options.value("game").toMap();
  const auto name = title.trimmed();
  const int port = options.value("port", 0).toInt();
  if (name.isEmpty() || name.size() > 80 || !QDir(directory).exists() || directory.isEmpty() ||
      options.value("instanceId").toString().isEmpty() ||
      game.value("version").toString().isEmpty() || port < 0 || port > 65535) {
    report(QCoreApplication::translate("Bugg", "请选择已安装的游戏并填写有效房间名称"));
    return;
  }
  const auto operation = ++room_generation_;
  room_directory_ = directory;
  // 原生引擎持有本机文件权限，节点 describe 不回传该字段；只在建房成功后发布。
  pending_room_ = {{"instanceId", options.value("instanceId")},
                   {"game", game},
                   {"allowSharing", options.value("cacheAcceleration", false).toBool()}};
  status_["worldsLoading"] = false;
  status_.remove("error");
  status_["roomBusy"] = true;
  status_["roomOperation"] = "create";
  emit changed();
  const auto host = [this, operation, name, directory, player, options, game, port](
                        const QJsonObject& world, const QString& error) {
    if (closing_ || operation != room_generation_) return;
    if (!error.isEmpty()) {
      complete_room(operation, {}, error);
      return;
    }
    auto metadata = QJsonObject::fromVariantMap(game);
    for (auto it = world.begin(); it != world.end(); ++it)
      if (it.key() != "version") metadata[it.key()] = it.value();
    const bool visible = options.value("public", true).toBool();
    bridge_.call(
        "room.host",
        {{"node", node_},
         {"transport", "auto"},
         {"game_port", port},
         {"game_directory", directory},
         {"chat_name", player.isEmpty() ? status_.value("username").toString() : player},
         {"settings",
          QJsonObject{{"title", name},
                      {"public", visible},
                      {"require_invite", !visible || options.value("requireInvite", true).toBool()},
                      {"allow_mod_transfer", options.value("cacheAcceleration", false).toBool()},
                      {"game", metadata}}}},
        [this, operation](const QJsonObject& room, const QString& error) {
          complete_room(operation, room, error);
        });
  };
  if (port)
    probe_world(port, game, host);
  else
    host({}, {});
}
void MultiplayerService::probe_world(int port, const QVariantMap& game,
                                     NativeBridge::Reply complete) {
  bridge_.call("game.status", {{"port", port}, {"timeout_ms", 4000}},
               [game, complete](const QJsonObject& world, const QString& error) {
                 auto detail = response_error(world, error);
                 if (!detail.isEmpty() || world["port"].toInt() <= 0)
                   detail = QCoreApplication::translate(
                       "Bugg",
                       "无法连接已开放的世界，请确认世界仍处于对局域网开放状态后重新查找。");
                 else if (!world_version_matches(world["version"].toString(),
                                                 game.value("version").toString()))
                   detail = QCoreApplication::translate(
                                "Bugg", "世界版本（%1）与所选游戏（%2）不一致，请选择对应的游戏。")
                                .arg(world["version"].toString(), game.value("version").toString());
                 complete(world, detail);
               });
}
void MultiplayerService::discover_worlds() {
  if (closing_ || node_.isEmpty() || status_.value("worldsLoading").toBool() ||
      status_.value("roomBusy").toBool() || room_probe_)
    return;
  const auto operation = room_generation_;
  const auto generation = generation_;
  status_["worldsLoading"] = true;
  status_.remove("error");
  emit changed();
  bridge_.call("game.discover", {{"duration_ms", 1500}},
               [this, operation, generation](const QJsonObject& value, const QString& error) {
                 if (closing_ || generation != generation_ || operation != room_generation_) return;
                 status_["worldsLoading"] = false;
                 const auto detail = response_error(value, error);
                 if (!detail.isEmpty()) {
                   status_["worlds"] = QVariantList{};
                   report(detail);
                   return;
                 }
                 const auto worlds = value["worlds"].toArray().toVariantList();
                 status_["worlds"] = worlds;
                 emit changed();
                 const auto room = status_.value("room").toMap();
                 if (room.value("role") != "host" || room.value("availability") == "ready") return;
                 // 仅唯一且版本相同的世界可自动关联；多个候选在房间页明确选择。
                 if (worlds.size() == 1 &&
                     world_version_matches(worlds[0].toMap().value("version").toString(),
                                           room.value("game").toMap().value("version").toString()))
                   connect_world(worlds[0].toMap().value("port").toInt());
               });
}
void MultiplayerService::connect_world(int port) {
  const auto room = status_.value("room").toMap();
  if (closing_ || session_.isEmpty() || room.value("role") != "host" || room_probe_ || port < 1 ||
      port > 65535)
    return;
  const auto operation = room_generation_;
  const auto session = session_;
  const auto game = room.value("game").toMap();
  room_probe_ = true;
  status_["worldBusy"] = true;
  emit changed();
  probe_world(
      port, game,
      [this, operation, session, game, port](const QJsonObject& world, const QString& error) {
        if (closing_ || operation != room_generation_ || session != session_) return;
        if (!error.isEmpty()) {
          room_probe_ = false;
          status_["worldBusy"] = false;
          report(error);
          return;
        }
        auto metadata = QJsonObject::fromVariantMap(game);
        for (auto it = world.begin(); it != world.end(); ++it)
          if (it.key() != "version") metadata[it.key()] = it.value();
        bridge_.call("room.retarget", {{"session", session}, {"port", port}, {"game", metadata}},
                     [this, operation, session](const QJsonObject& value, const QString& failure) {
                       if (closing_ || operation != room_generation_ || session != session_) return;
                       room_probe_ = false;
                       status_["worldBusy"] = false;
                       const auto detail = response_error(value, failure);
                       if (!detail.isEmpty())
                         report(detail);
                       else {
                         status_.remove("error");
                         heartbeat();
                       }
                     });
      });
}
bool MultiplayerService::copy_invite() {
  const auto invite = status_.value("room").toMap().value("invite").toString();
  if (invite.isEmpty()) return false;
  QGuiApplication::clipboard()->setText(invite);
  return true;
}
void MultiplayerService::join_room(const QString& invite) {
  if (closing_ || node_.isEmpty() || !session_.isEmpty() || status_.value("roomBusy").toBool())
    return;
  if (invite.trimmed().isEmpty()) {
    report(QCoreApplication::translate("Bugg", "请输入房间邀请"));
    return;
  }
  const auto operation = ++room_generation_;
  status_.remove("error");
  status_["worldsLoading"] = false;
  status_["roomBusy"] = true;
  status_["roomOperation"] = "join";
  emit changed();
  bridge_.call("room.join",
               {{"node", node_},
                {"invite", invite.trimmed()},
                {"transport", "auto"},
                {"announce", false},
                {"chat_name", status_.value("username").toString()}},
               [this, operation](const QJsonObject& value, const QString& error) {
                 complete_room(operation, value, error);
               });
}
void MultiplayerService::join_listing(const QString& id) {
  if (closing_ || node_.isEmpty() || !session_.isEmpty() || status_.value("roomBusy").toBool())
    return;
  const auto operation = ++room_generation_;
  status_["roomBusy"] = true;
  status_["roomOperation"] = "join";
  status_["worldsLoading"] = false;
  status_.remove("error");
  emit changed();
  bridge_.call(
      "room.resolve", {{"node", node_}, {"id", id}},
      [this, operation, id](const QJsonObject& value, const QString& error) {
        if (closing_ || operation != room_generation_) return;
        status_["roomBusy"] = false;
        const auto detail = response_error(value, error);
        if (!detail.isEmpty() || value["secret"].toString().isEmpty()) {
          status_.remove("roomOperation");
          const auto code = detail.section(": ", -1);
          if (code == "not_found" || code == "expired" || code == "unpublished" ||
              detail == "Room unavailable") {
            auto rooms = status_.value("rooms").toList();
            rooms.removeIf([&id](const QVariant& room) { return room.toMap().value("id") == id; });
            status_["rooms"] = rooms;
            report(QCoreApplication::translate(
                "Bugg", "房间已失效或尚未发布，已从大厅移除。请让房主重新创建或发送邀请。"));
          } else if (code == "invitation_required" ||
                     detail == "Room requires a current invitation") {
            report(QCoreApplication::translate("Bugg", "此房间需要邀请，请向房主获取邀请后加入。"));
          } else if (code == "node_unavailable") {
            report(QCoreApplication::translate("Bugg", "房间节点暂时不可达，请稍后重试。"));
          } else {
            report(QCoreApplication::translate("Bugg", "暂时无法获取房间信息，请稍后重试。"));
          }
          return;
        }
        join_room("bugg1-" + value["secret"].toString());
      });
}
void MultiplayerService::leave_room() {
  ++room_generation_;
  ++content_revision_;
  if (!session_.isEmpty()) emit content_invalidated(session_);
  if (cache_cancelled_) cache_cancelled_->store(true);
  cache_key_.clear();
  room_directory_.clear();
  status_.remove("cacheProgress");
  preparation_timer_.stop();
  preparation_ = {};
  preparation_pending_ = false;
  preparation_task_.clear();
  launch_task_.clear();
  room_poll_.stop();
  announcement_.stop();
  event_pending_ = false;
  message_ids_.clear();
  status_.remove("messages");
  status_.remove("chatError");
  status_["chatBusy"] = false;
  pending_room_.clear();
  cancel_invites();
  const auto session = std::exchange(session_, {});
  room_probe_ = false;
  const auto retired = std::exchange(retired_nodes_, {});
  if (!session.isEmpty())
    bridge_.call("room.close", {{"session", session}}, [this, retired](const auto&, const auto&) {
      for (const auto& node : retired)
        bridge_.call("node.remove", {{"node", node}}, [](const auto&, const auto&) {});
    });
  status_.remove("room");
  status_.remove("outgoingInvitations");
  status_["roomBusy"] = false;
  status_["worldBusy"] = false;
  status_["worldsLoading"] = false;
  status_["roomCommandBusy"] = false;
  emit changed();
  if (!session.isEmpty()) emit room_left();
}
void MultiplayerService::social(const QString& operation, const QString& target,
                                const QVariantMap& fields) {
  if (operation == "ignore") {
    const auto ref = fields.value("ref").toString();
    if (ref.isEmpty()) return;
    ignored_invites_.insert(ref);
    auto invitations = status_.value("invitations").toList();
    invitations.removeIf([&ref](const QVariant& item) { return item.toMap().value("id") == ref; });
    status_["invitations"] = invitations;
    update_notifications();
    emit changed();
    return;
  }
  if (closing_ || node_.isEmpty() || status_.value("socialBusy").toBool() ||
      !QStringList{"request", "accept", "remove", "invite", "join", "request_join", "accept_join",
                   "decline_join"}
           .contains(operation))
    return;
  const auto identifier = target.trimmed();
  if (operation == "request" && !account_id(identifier)) {
    static const QRegularExpression pattern("^[A-Za-z0-9_-]{3,32}$");
    if (!pattern.match(identifier).hasMatch()) {
      report(QCoreApplication::translate("Bugg", "请输入好友码或用户名"));
      return;
    }
    const auto lookup = ++lookup_generation_;
    const auto generation = generation_;
    status_["lookupResults"] = QVariantList{};
    status_["socialBusy"] = true;
    status_["lookupBusy"] = true;
    status_.remove("error");
    emit changed();
    bridge_.call(
        "node.request",
        {{"node", node_},
         {"request", QJsonObject{{"op", "account_lookup"}, {"identifier", identifier}}}},
        [this, lookup, generation, identifier](const QJsonObject& value, const QString& error) {
          if (closing_ || generation != generation_ || lookup != lookup_generation_) return;
          status_["lookupBusy"] = false;
          status_["socialBusy"] = false;
          auto detail = response_error(value, error);
          QVariantList candidates;
          const auto accounts = value["accounts"].toArray();
          if (detail.isEmpty()) {
            for (const auto& entry : accounts) {
              const auto item = entry.toObject();
              const auto account = item["account"].toString(), name = item["username"].toString();
              auto code = friend_code(account);
              code.remove('-');
              auto query = identifier;
              query.remove('-');
              if (!account_id(account) || (name.compare(identifier, Qt::CaseInsensitive) != 0 &&
                                           code.compare(query, Qt::CaseInsensitive) != 0)) {
                detail = QCoreApplication::translate("Bugg", "账号查询结果无效，请重试");
                break;
              }
              candidates.append(QVariantMap{
                  {"account", account}, {"username", name}, {"friendCode", friend_code(account)}});
            }
            if (accounts.size() > 8)
              detail = QCoreApplication::translate("Bugg", "账号查询结果无效，请重试");
            if (candidates.isEmpty())
              detail = QCoreApplication::translate("Bugg", "未找到账号，请核对好友码或用户名");
          }
          if (!detail.isEmpty()) {
            report(detail);
            return;
          }
          if (candidates.size() == 1)
            social("request", candidates[0].toMap().value("account").toString());
          else {
            status_["lookupResults"] = candidates;
            emit changed();
          }
        });
    return;
  }
  if (!account_id(identifier) || identifier == status_.value("account").toString()) {
    report(QCoreApplication::translate("Bugg", "请选择有效的好友账号"));
    return;
  }
  const auto generation = generation_;
  QVariantMap signed_fields;
  const auto room_generation = room_generation_;
  if (QStringList{"accept", "join", "accept_join", "decline_join"}.contains(operation))
    signed_fields["ref"] = fields.value("ref");
  if (QStringList{"invite", "request_join", "accept_join", "decline_join"}.contains(operation))
    signed_fields["room"] = fields.value("room");
  status_["socialBusy"] = true;
  status_.remove("error");
  emit changed();
  bridge_.call(
      "social.operate",
      {{"node", node_},
       {"operation", operation},
       {"target", identifier},
       {"fields", QJsonObject::fromVariantMap(signed_fields)}},
      [this, generation, room_generation, operation, target](const QJsonObject& value,
                                                             const QString& error) {
        if (!closing_ && generation == generation_) {
          status_["socialBusy"] = false;
          if (QStringList{"invite", "join", "request_join", "accept_join", "decline_join"}.contains(
                  operation) &&
              room_generation != room_generation_) {
            emit changed();
            dispatch_invites();
            return;
          }
          const auto detail = response_error(value, error);
          report(detail);
          if (operation == "invite") {
            auto outgoing = status_.value("outgoingInvitations").toMap();
            outgoing[target] = detail.isEmpty() ? "sent" : "failed";
            status_["outgoingInvitations"] = outgoing;
          }
          if (detail.isEmpty()) {
            if (operation == "join")
              join_room(value["invite"].toString());
            else
              apply_social(value);
            emit social_completed(operation, target);
          }
          emit changed();
          dispatch_invites();
        }
      });
}
void MultiplayerService::apply_social(const QJsonObject& value) {
  if (!account_id(value["account"].toString())) return;
  for (const auto* field : {"friends", "requests", "invitations", "joinRequests"})
    status_[field] = value[field].toArray().toVariantList();
  auto invitations = status_.value("invitations").toList();
  invitations.removeIf([this](const QVariant& item) {
    return ignored_invites_.contains(item.toMap().value("id").toString());
  });
  status_["invitations"] = invitations;
  status_["account"] = value["account"].toString();
  status_["username"] = value["username"].toString();
  status_["capabilities"] = value["capabilities"].toObject().toVariantMap();
  status_["friendCode"] = friend_code(value["account"].toString());
  update_notifications();
  emit changed();
}
void MultiplayerService::update_notifications() {
  QHash<QString, QVariantMap> previous;
  for (const auto& entry : status_.value("notifications").toList()) {
    const auto item = entry.toMap();
    previous.insert(item.value("notificationKind").toString() + ':' + item.value("id").toString(),
                    item);
  }
  QVariantList notifications;
  int unread = 0;
  const auto received = QDateTime::currentMSecsSinceEpoch();
  for (const auto* field : {"requests", "invitations", "joinRequests"}) {
    const auto kind = QString(field) == "joinRequests" ? QString("joins") : QString(field);
    for (const auto& entry : status_.value(field).toList()) {
      auto item = entry.toMap();
      if (kind == "joins" &&
          (!item.value("incoming").toBool() || item.value("status") != "pending"))
        continue;
      const auto old = previous.value(kind + ':' + item.value("id").toString());
      item["notificationKind"] = kind;
      item["receivedAt"] = old.value("receivedAt", received);
      item["unread"] = old.value("unread", kind != "requests" || item.value("incoming").toBool());
      unread += item.value("unread").toBool();
      notifications.append(item);
    }
  }
  std::stable_sort(notifications.begin(), notifications.end(),
                   [](const auto& first, const auto& second) {
                     return first.toMap().value("receivedAt").toLongLong() >
                            second.toMap().value("receivedAt").toLongLong();
                   });
  status_["notifications"] = notifications;
  status_["notificationCount"] = unread;
  if (!notifications.isEmpty())
    status_["notificationAt"] =
        std::max(status_.value("notificationAt").toLongLong(),
                 notifications.first().toMap().value("receivedAt").toLongLong());
  for (const auto* category : {"rooms", "requests"}) {
    const QString prefix = QString(category) == "rooms" ? "roomNotification" : "friendRequest";
    int count = 0;
    auto latest = status_.value(prefix + "At").toLongLong();
    for (const auto& entry : notifications) {
      const auto item = entry.toMap();
      if ((item.value("notificationKind") == "requests") != (QString(category) == "requests"))
        continue;
      count += item.value("unread").toBool();
      latest = std::max(latest, item.value("receivedAt").toLongLong());
    }
    status_[prefix + "Count"] = count;
    status_[prefix + "At"] = latest;
  }
}
void MultiplayerService::mark_notifications_read(const QString& category) {
  if (!status_.value("notificationCount").toInt()) return;
  auto notifications = status_.value("notifications").toList();
  bool modified = false;
  for (auto& entry : notifications) {
    auto item = entry.toMap();
    if (!category.isEmpty() &&
        ((item.value("notificationKind") == "requests") != (category == "requests")))
      continue;
    modified |= item.value("unread").toBool();
    item["unread"] = false;
    entry = item;
  }
  status_["notifications"] = notifications;
  if (!modified) return;
  update_notifications();
  emit changed();
}
void MultiplayerService::cancel_lookup() {
  ++lookup_generation_;
  if (status_.value("lookupBusy").toBool()) status_["socialBusy"] = false;
  status_["lookupBusy"] = false;
  status_["lookupResults"] = QVariantList{};
  emit changed();
}
bool MultiplayerService::copy_friend_code(const QString& account) {
  const auto code = friend_code(account.isEmpty() ? status_.value("account").toString() : account);
  if (code.isEmpty()) return false;
  QGuiApplication::clipboard()->setText(code);
  return true;
}
void MultiplayerService::invite_friend(const QString& account) {
  if (closing_ || node_.isEmpty() || pending_invites_.contains(account)) return;
  const auto friends = status_.value("friends").toList();
  const auto found = std::find_if(friends.begin(), friends.end(), [&account](const QVariant& item) {
    const auto friend_item = item.toMap();
    return friend_item.value("account") == account && friend_item.value("online").toBool();
  });
  if (found == friends.end()) {
    report(QCoreApplication::translate("Bugg", "好友当前不在线"));
    return;
  }
  const auto room = status_.value("room").toMap();
  if (!room.isEmpty() && !room.value("isManager", room.value("role") == "host").toBool()) {
    report(QCoreApplication::translate("Bugg", "请由房主邀请好友"));
    return;
  }
  pending_invites_.append(account);
  status_["pendingInvites"] = pending_invites_;
  emit changed();
  dispatch_invites();
  if (room.value("availability") != "ready") emit host_required();
}
void MultiplayerService::cancel_invites() {
  pending_invites_.clear();
  status_["pendingInvites"] = QStringList{};
  emit changed();
}
void MultiplayerService::dispatch_invites() {
  const auto room = status_.value("room").toMap();
  if (closing_ || pending_invites_.isEmpty() || status_.value("socialBusy").toBool() ||
      room.value("availability") != "ready")
    return;
  const auto account = pending_invites_.takeFirst();
  status_["pendingInvites"] = pending_invites_;
  auto outgoing = status_.value("outgoingInvitations").toMap();
  outgoing[account] = "sending";
  status_["outgoingInvitations"] = outgoing;
  social("invite", account, {{"room", room.value("id")}});
}
void MultiplayerService::room_command(const QString& operation, const QVariantMap& fields) {
  if (closing_ || session_.isEmpty() || status_.value("roomCommandBusy").toBool() ||
      !QStringList{"configure", "member_kick", "member_unblock", "owner_offer", "owner_answer",
                   "owner_cancel"}
           .contains(operation))
    return;
  const auto generation = room_generation_;
  status_["roomCommandBusy"] = true;
  status_.remove("error");
  emit changed();
  auto request = QJsonObject::fromVariantMap(fields);
  if (operation == "configure" && status_.value("room").toMap().value("role") == "host") {
    const auto room = status_.value("room").toMap();
    if (!request.contains("game"))
      request["game"] = QJsonObject::fromVariantMap(room.value("game").toMap());
    if (!request.contains("allow_mod_transfer"))
      request["allow_mod_transfer"] = room.value("allowSharing", false).toBool();
  }
  if (operation != "configure") request["op"] = operation;
  bridge_.call(
      operation == "configure" ? "room.configure" : "room.request",
      {{"session", session_}, {operation == "configure" ? "settings" : "request", request}},
      [this, generation, operation, request](const QJsonObject& value, const QString& error) {
        if (closing_ || generation != room_generation_) return;
        status_["roomCommandBusy"] = false;
        const auto detail = response_error(value, error);
        if (detail.isEmpty() && operation == "configure" &&
            request.contains("allow_mod_transfer")) {
          auto room = status_.value("room").toMap();
          room["allowSharing"] = request["allow_mod_transfer"].toBool();
          status_["room"] = room;
          update_acceleration();
        }
        report(detail);
        if (detail.isEmpty()) {
          emit room_command_completed(operation);
          heartbeat();
        }
      });
}
void MultiplayerService::update_acceleration() {
  const auto room = status_.value("room").toMap();
  const auto game = QJsonObject::fromVariantMap(room.value("game").toMap());
  const bool enabled = !closing_ && !session_.isEmpty() && room.value("role") == "host" &&
                       room.value("allowSharing").toBool();
  const auto key = session_ + QString::fromUtf8(QJsonDocument(game).toJson(QJsonDocument::Compact));
  if (enabled && cache_key_ == key && cache_cancelled_ && !cache_cancelled_->load()) return;
  if (cache_cancelled_) cache_cancelled_->store(true);
  if (!enabled) {
    cache_key_.clear();
    status_.remove("cacheProgress");
    return;
  }
  // 前一配置释放源站租约后才启用新配置，保持同一房间只有一个补传者。
  if (cache_workers_) return;
  cache_key_ = key;
  cache_cancelled_ = std::make_shared<std::atomic_bool>(false);
  const auto cancelled = cache_cancelled_;
  const auto generation = room_generation_;
  const auto session = session_;
  const auto directory = room_directory_;
  auto* watcher = new QFutureWatcher<void>(this);
  ++cache_workers_;
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
    watcher->deleteLater();
    --cache_workers_;
    update_acceleration();
    if (closing_ && !busy()) emit drained();
  });
  watcher->setFuture(
      QtConcurrent::run([this, watcher, cancelled, generation, session, directory, game] {
        RoomContentCache content(
            [this](const auto& method, auto parameters, const auto& cancel) {
              return content_request(method, parameters, cancel);
            },
            session, cancelled,
            [this, watcher, cancelled, generation](const QVariantMap& progress) {
              QMetaObject::invokeMethod(
                  watcher,
                  [this, cancelled, generation, progress] {
                    if (closing_ || cancelled->load() || generation != room_generation_) return;
                    status_["cacheProgress"] = progress;
                    emit changed();
                  },
                  Qt::QueuedConnection);
            });
        content.host(directory, game);
      }));
}
void MultiplayerService::preparation_progress(const QString& session, const QString& task,
                                              const QString& state, double progress,
                                              const QString& task_config) {
  if (closing_ || session_.isEmpty() || session != session_) return;
  auto room = status_.value("room").toMap();
  if (!task_config.isEmpty() &&
      task_config != room.value("lobby").toMap().value("config_id").toString())
    return;
  if (!task.isEmpty() && task != launch_task_) {
    room["syncState"] =
        QStringList{"ready", "failed", "cancelled"}.contains(state) ? state : "running";
    status_["room"] = room;
    emit changed();
  }
  const auto config =
      status_.value("room").toMap().value("lobby").toMap().value("config_id").toString();
  if (config.isEmpty()) return;
  if (!task.isEmpty()) preparation_task_ = task;
  preparation_ = {{"op", "member_update"},
                  {"config_id", config},
                  {"task", preparation_task_},
                  {"state", state},
                  {"stage", "game"},
                  {"seq", double(++preparation_sequence_)},
                  {"done", progress >= 0 ? qBound(0, int(progress * 1000), 1000) : 0},
                  {"total", progress >= 0 ? 1000 : 0}};
  if (!preparation_timer_.isActive() && !preparation_pending_) preparation_timer_.start();
}
void MultiplayerService::report_preparation() {
  if (closing_ || session_.isEmpty() || preparation_.isEmpty() || preparation_pending_) return;
  const auto generation = room_generation_;
  preparation_pending_ = true;
  const auto fields = std::exchange(preparation_, {});
  bridge_.call("room.request", {{"session", session_}, {"request", fields}},
               [this, generation](const auto&, const auto&) {
                 if (closing_ || generation != room_generation_) return;
                 preparation_pending_ = false;
                 if (!preparation_.isEmpty()) preparation_timer_.start();
               });
}
void MultiplayerService::launch_progress(const QVariantMap& status) {
  launch_status_ = status;
  auto room = status_.value("room").toMap();
  if (status.value("instanceName").toString().isEmpty() ||
      status.value("instanceName") != room.value("instanceId"))
    return;
  const auto state = status.value("state").toString();
  if (state == "failed" && room.value("role") != "host" &&
      status.value("detail").toString().startsWith(
          QCoreApplication::translate("Bugg", "房间配置已改变，请重新同步"))) {
    room.remove("instanceId");
    room["compatibility"] = status.value("detail");
    status_["room"] = room;
    emit changed();
    emit preparation_required();
  }
  const auto member_state = state == "preparing" ? "starting"
                            : state == "running" ? "playing"
                            : state == "failed"  ? "failed"
                                                 : "ready";
  if (launch_task_.isEmpty()) launch_task_ = "launch-" + QString::number(++preparation_sequence_);
  preparation_progress(session_, launch_task_, member_state,
                       status.value("progress", -1).toDouble());
  if (state == "idle" || state == "failed") launch_task_.clear();
}
void MultiplayerService::shutdown() {
  if (feedback_request_) http_->cancel(std::exchange(feedback_request_, 0));
  closing_ = true;
  if (cache_cancelled_) cache_cancelled_->store(true);
  preparation_timer_.stop();
  ++generation_;
  polling_.stop();
  heartbeat_.stop();
  room_poll_.stop();
  announcement_.stop();
  if (request_) http_->cancel(std::exchange(request_, 0));
  response_ = {};
  bridge_.shutdown();
  if (!busy()) emit drained();
}
}  // namespace bugg
