#include "modules/room_sync/application/room_content_cache.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileInfo>
#include <QJsonDocument>
#include <QLocale>
#include <QRegularExpression>
#include <QSet>
#include <QThread>
#include <QTimer>

namespace bugg {
RoomContentCache::RoomContentCache(RoomContentRequest request, QString session,
                                   Cancellation cancelled, Progress progress, HttpClient* transport)
    : request_(std::move(request)),
      session_(std::move(session)),
      cancelled_(std::move(cancelled)),
      progress_(std::move(progress)),
      transport_(transport ? transport : &http_) {}

QJsonObject RoomContentCache::transfer(const QString& method, QJsonObject parameters) {
  parameters["session"] = session_;
  QJsonObject result;
  QString id;
  QElapsedTimer clock;
  clock.start();
  try {
    result = request_(method, parameters, cancelled_);
    id = result["transfer"].toString();
    while (result["state"] != "complete") {
      check_cancelled(cancelled_);
      if (result["state"] == "error" || id.isEmpty() || clock.elapsed() > 180000)
        throw std::runtime_error(
            result["error"].toString("Room content transfer failed").toStdString());
      QThread::msleep(100);
      result = request_("mods.status", {{"session", session_}, {"transfer", id}}, cancelled_);
    }
    if (result.contains("items")) {
      auto items = result["items"].toArray();
      const auto total = result["total"].toInt(-1);
      if (total < 0 || total > 2000) throw std::runtime_error("Invalid room manifest total");
      while (items.size() < total) {
        auto page = parameters;
        page["offset"] = items.size();
        if (!id.isEmpty()) page["transfer"] = id;
        const auto next = request_(id.isEmpty() ? method : "mods.status", page, cancelled_);
        if (next["offset"].toInt(-1) != items.size() || next["total"].toInt(-1) != total ||
            next["items"].toArray().isEmpty())
          throw std::runtime_error("Incomplete room manifest page");
        for (const auto& item : next["items"].toArray()) items.append(item);
      }
      if (items.size() != total) throw std::runtime_error("Oversized room manifest");
      result["items"] = items;
    }
  } catch (...) {
    if (!id.isEmpty()) {
      try {
        request_("mods.cancel", {{"session", session_}, {"transfer", id}},
                 std::make_shared<std::atomic_bool>(false));
      } catch (...) {
      }
    }
    throw;
  }
  if (!id.isEmpty()) request_("mods.cancel", {{"session", session_}, {"transfer", id}}, cancelled_);
  return result;
}
QJsonObject RoomContentCache::perform(HttpRequest request, const Cancellation& cancelled) {
  check_cancelled(cancelled);
  QEventLoop loop;
  QTimer cancel;
  cancel.setInterval(50);
  QString error;
  QJsonObject result;
  const auto id = transport_->request(request);
  const auto response = QObject::connect(
      transport_, &HttpClient::response, &loop,
      [&](quint64 received, const QByteArray& bytes, const QString& failure, int status) {
        if (received != id) return;
        error = failure;
        result = QJsonDocument::fromJson(bytes).object();
        if (error.isEmpty() && status >= 400) error = QString("HTTP %1").arg(status);
        loop.quit();
      });
  const auto progress = QObject::connect(
      transport_, &HttpClient::progress, &loop, [&](quint64 received, qint64 done, qint64 total) {
        if (received == id && !request.input_path.isEmpty())
          publish("uploading", QFileInfo(request.input_path).fileName(), uploaded_bytes_ + done,
                  upload_bytes_);
      });
  QObject::connect(&cancel, &QTimer::timeout, &loop, [&] {
    if (cancelled->load()) {
      transport_->cancel(id);
      loop.quit();
    }
  });
  cancel.start();
  loop.exec();
  QObject::disconnect(response);
  QObject::disconnect(progress);
  check_cancelled(cancelled);
  if (!error.isEmpty()) throw std::runtime_error(error.toStdString());
  return result;
}
QJsonArray RoomContentCache::manifest(const QJsonObject& game) {
  QJsonArray files;
  QSet<QString> names;
  qint64 bytes = 0;
  for (const auto& kind : {QString("mods"), QString("resources")}) {
    const auto count = game[kind + "_count"].toInt(-1);
    if (count < 0 || count > 2000) throw std::runtime_error("Invalid room manifest count");
    QJsonArray items;
    if (count) {
      try {
        items = transfer("mods.manifest", {{"kind", kind}})["items"].toArray();
      } catch (...) {
        check_cancelled(cancelled_);
        items = game[kind].toArray();
      }
    }
    QStringList hashes;
    for (const auto& value : items) {
      auto item = value.toObject();
      const auto path =
          kind == "mods" ? "mods/" + item["name"].toString() : item["path"].toString();
      const auto parts = path.split('/');
      const auto size = item["size"].toDouble(-1);
      if (parts.size() != 2 || parts.last().isEmpty() || parts.last() == "." ||
          parts.last() == ".." || path.contains(QRegularExpression("[\\\\:\\x00-\\x1f]")) ||
          names.contains(path.toCaseFolded()) ||
          (kind == "mods"
               ? parts.first() != "mods" || !parts.last().endsWith(".jar", Qt::CaseInsensitive)
               : !QStringList{"resourcepacks", "shaderpacks"}.contains(parts.first())) ||
          size < 0 || size > 512.0 * 1024 * 1024 ||
          !QRegularExpression("^[0-9a-f]{64}$").match(item["sha256"].toString()).hasMatch())
        throw std::runtime_error("Invalid room content path, size or digest");
      names.insert(path.toCaseFolded());
      bytes += qint64(size);
      if (bytes > 8ll * 1024 * 1024 * 1024)
        throw std::runtime_error("Room content exceeds size limit");
      hashes.append(item["sha256"].toString());
      item["path"] = path;
      item["kind"] = kind;
      files.append(item);
    }
    hashes.sort();
    if (hashes.size() != count ||
        QString::fromLatin1(
            QCryptographicHash::hash(hashes.join('\n').toUtf8(), QCryptographicHash::Sha256)
                .toHex()) != game[kind + "_hash"])
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "房间文件清单不完整或已改变，请重试").toStdString());
  }
  return files;
}
QJsonObject RoomContentCache::grant(bool host) {
  if (grant_["expires_at"].toDouble() > QDateTime::currentSecsSinceEpoch() + 30) return grant_;
  auto request = QJsonObject{{"op", "content_cache_grant"}};
  if (host) request["share"] = true;
  auto value = request_("room.request", {{"session", session_}, {"request", request}}, cancelled_);
  const QUrl url(value["url"].toString());
  if (value["protocol"] != "room-content-cache-v1" || url.scheme() != "https" ||
      url.host().isEmpty() || !url.userInfo().isEmpty() || (url.port(443) != 443) ||
      (!url.path().isEmpty() && url.path() != "/") || url.hasQuery() || url.hasFragment() ||
      (host && (value["token"].toString().isEmpty() || value["token"].toString().size() > 2048)))
    throw std::runtime_error("Invalid room cache grant");
  grant_ = value;
  return grant_;
}
QJsonObject RoomContentCache::query(const QString& path, const QJsonObject& body, bool authorized) {
  HttpRequest request;
  request.url = QUrl(grant(authorized)["url"].toString()).resolved(QUrl(path));
  request.method = "POST";
  request.body = QJsonDocument(body).toJson(QJsonDocument::Compact);
  request.maximum_bytes = 2 * 1024 * 1024;
  request.headers["Content-Type"] = "application/json";
  if (authorized)
    request.headers["Authorization"] = "Bearer " + grant_["token"].toString().toUtf8();
  const auto result = perform(request, cancelled_);
  if (result["protocol"] != "room-content-cache-v1" || !result["files"].isArray())
    throw std::runtime_error("Invalid room cache plan");
  return result;
}
QList<QUrl> RoomContentCache::sources(const QJsonObject& item) {
  QList<QUrl> urls;
  if (unavailable_) return urls;
  try {
    const auto digest = item["sha256"].toString();
    if (!QRegularExpression("^[0-9a-f]{64}$").match(digest).hasMatch()) return urls;
    const auto plan = query("/room-cache/resolve", {{"wanted", QJsonArray{digest}}}, false);
    for (const auto& value : plan["files"].toArray()) {
      const auto file = value.toObject();
      if (file["sha256"] != digest || file["size"] != item["size"]) continue;
      if (file["action"] == "cached")
        urls.append(QUrl(grant_["url"].toString()).resolved(QUrl("/room-cache/files/" + digest)));
      else if (file["action"] == "redirect")
        for (const auto& candidate : file["downloads"].toArray()) {
          const QUrl url(candidate.toString());
          if (url.scheme() == "https" && url.userInfo().isEmpty() && !url.hasFragment())
            urls.append(url);
        }
    }
  } catch (...) {
    check_cancelled(cancelled_);
    if (grant_.isEmpty()) unavailable_ = true;
  }
  return urls;
}
void RoomContentCache::publish(const QString& state, const QString& detail, qint64 done,
                               qint64 total) {
  const auto summary = snapshot_.value("summary").toMap();
  QString caption;
  if (!summary.isEmpty())
    caption = QCoreApplication::translate("Bugg", "已缓存 %1 / %2 · 公开源 %3 · 待处理 %4")
                  .arg(summary.value("cached").toInt())
                  .arg(summary.value("total").toInt())
                  .arg(summary.value("redirect").toInt())
                  .arg(summary.value("pending").toInt() + summary.value("upload").toInt());
  const auto cached_files = snapshot_.value("cachedFiles").toStringList();
  if (state == "ready" && !cached_files.isEmpty()) {
    auto visible_files = cached_files.mid(0, 2).join("、");
    if (cached_files.size() > 2)
      visible_files +=
          QCoreApplication::translate("Bugg", " 等 %1 个文件").arg(cached_files.size());
    caption += "\n" + QCoreApplication::translate("Bugg", "已缓存：%1").arg(visible_files);
  }
  if (!detail.isEmpty()) caption += (caption.isEmpty() ? "" : "\n") + detail;
  if (state == "uploading" && total > 0)
    caption +=
        " · " + QLocale().formattedDataSize(done) + " / " + QLocale().formattedDataSize(total);
  const bool active = state != "ready" && state != "empty" && state != "unavailable";
  snapshot_["state"] = state;
  snapshot_["label"] = state == "uploading"     ? QCoreApplication::translate("Bugg", "上传中")
                       : state == "ready"       ? QCoreApplication::translate("Bugg", "已就绪")
                       : state == "empty"       ? QCoreApplication::translate("Bugg", "无需缓存")
                       : state == "unavailable" ? QCoreApplication::translate("Bugg", "未连接")
                                                : QCoreApplication::translate("Bugg", "等待源站");
  snapshot_["detail"] = caption;
  snapshot_["active"] = active;
  snapshot_["done"] = done;
  snapshot_["total"] = total;
  snapshot_["progress"] = total > 0 ? qBound(0.0, double(done) / total, 1.0) : -1;
  if (progress_ && !cancelled_->load()) progress_(snapshot_);
}
void RoomContentCache::host(const QString& directory, const QJsonObject& game) {
  try {
    publish("scanning", QCoreApplication::translate("Bugg", "检查加速文件"));
    auto files = manifest(game);
    QHash<QString, QJsonObject> by_hash;
    for (qsizetype i = 0; i < files.size(); ++i) {
      auto item = files[i].toObject();
      item.remove("kind");
      item["downloads"] = QJsonArray{};
      files[i] = item;
      safe_path(directory, item["path"].toString());
      by_hash[item["sha256"].toString()] = item;
    }
    if (files.isEmpty()) {
      publish("empty", QCoreApplication::translate("Bugg", "没有需要缓存的模组或资源文件"));
      return;
    }
    bool published = false;
    publish("planning", QCoreApplication::translate("Bugg", "连接加速缓存服务"));
    while (!cancelled_->load()) {
      try {
        const auto plan = query("/room-cache/plan",
                                published ? QJsonObject{} : QJsonObject{{"files", files}}, true);
        published = plan["state"] != "waiting";
        snapshot_.remove("error");
        auto summary = plan["summary"].toObject();
        snapshot_["summary"] = summary.toVariantMap();
        QStringList cached_files;
        for (const auto& value : plan["files"].toArray()) {
          const auto file = value.toObject();
          if (file["action"] == "cached") cached_files.append(file["path"].toString());
        }
        snapshot_["cachedFiles"] = cached_files;
        const auto uploads = plan["upload"].toArray();
        uploaded_bytes_ = 0;
        upload_bytes_ = 0;
        for (const auto& value : uploads)
          upload_bytes_ += value.toObject()["size"].toVariant().toLongLong();
        for (const auto& value : uploads) {
          check_cancelled(cancelled_);
          const auto wanted = value.toObject();
          const auto hash = wanted["sha256"].toString();
          const auto file = by_hash.value(hash);
          if (file.isEmpty() || file["size"] != wanted["size"])
            throw std::runtime_error("Source requested an unlisted file");
          const auto path = safe_path(directory, file["path"].toString());
          if (QFileInfo(path).size() != file["size"].toVariant().toLongLong() ||
              file_digest(path, "sha256", cancelled_) != hash.toLatin1())
            throw std::runtime_error("Acceleration file changed");
          HttpRequest upload;
          upload.url =
              QUrl(grant(true)["url"].toString()).resolved(QUrl("/room-cache/files/" + hash));
          upload.method = "PUT";
          upload.input_path = path;
          upload.total_ms = 30 * 60 * 1000;
          upload.headers["Authorization"] = "Bearer " + grant_["token"].toString().toUtf8();
          upload.headers["Content-Type"] = "application/octet-stream";
          upload.headers["Content-Length"] = QByteArray::number(QFileInfo(path).size());
          publish("uploading", file["path"].toString(), uploaded_bytes_, upload_bytes_);
          const auto receipt = perform(upload, cancelled_);
          if (receipt["state"] != "cached" || receipt["sha256"] != hash ||
              receipt["size"] != file["size"])
            throw std::runtime_error("Source did not confirm cached file");
          uploaded_bytes_ += file["size"].toVariant().toLongLong();
          summary["cached"] = summary["cached"].toInt() + 1;
          summary["upload"] = qMax(0, summary["upload"].toInt() - 1);
          snapshot_["summary"] = summary.toVariantMap();
          publish("uploading", file["path"].toString(), uploaded_bytes_, upload_bytes_);
        }
        // 收据确认只代表这些文件成功；立即重查计划，不能拿上传前的汇总宣称全部就绪。
        if (!uploads.isEmpty()) continue;
        if (plan["state"] == "waiting" || summary["pending"].toInt() > 0) {
          QString reason;
          for (const auto& value : plan["files"].toArray()) {
            const auto file = value.toObject();
            if (file["action"] == "pending" && !file["reason"].toString().isEmpty()) {
              reason = file["reason"].toString();
              break;
            }
          }
          publish("pending", reason.isEmpty()
                                 ? QCoreApplication::translate("Bugg", "源站正在准备下载加速")
                                 : reason);
        } else {
          publish("ready", summary["cached"].toInt() == 0
                               ? QCoreApplication::translate("Bugg", "公开源可直接下载，无需上传")
                               : QString());
        }
      } catch (const std::exception& error) {
        check_cancelled(cancelled_);
        const auto failure = QString::fromUtf8(error.what());
        snapshot_["error"] = failure;
        snapshot_.remove("summary");
        snapshot_.remove("cachedFiles");
        publish("unavailable",
                failure.contains("configured on this node")
                    ? QCoreApplication::translate("Bugg", "节点未配置加速缓存服务")
                    : QCoreApplication::translate("Bugg", "缓存服务暂不可用，正在重试"));
      }
      for (int i = 0; i < 50; ++i) {
        check_cancelled(cancelled_);
        QThread::msleep(100);
      }
    }
  } catch (const std::exception& error) {
    snapshot_["error"] = QString::fromUtf8(error.what());
    publish("unavailable", QCoreApplication::translate("Bugg", "无法读取房间文件，请重新选择游戏"));
  }
  if (!grant_["token"].toString().isEmpty()) {
    try {
      HttpRequest release;
      release.url = QUrl(grant_["url"].toString()).resolved(QUrl("/room-cache/release"));
      release.method = "POST";
      release.body = "{}";
      release.headers["Authorization"] = "Bearer " + grant_["token"].toString().toUtf8();
      release.headers["Content-Type"] = "application/json";
      release.total_ms = 2000;
      perform(release, std::make_shared<std::atomic_bool>(false));
    } catch (...) {
    }
  }
}
}  // namespace bugg
