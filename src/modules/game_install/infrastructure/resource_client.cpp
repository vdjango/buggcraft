#include "modules/game_install/infrastructure/resource_client.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocale>
#include <QSet>
#include <QTimer>
#include <algorithm>
#include <stdexcept>

#include "contracts/download_sources.h"
#include "platform/diagnostics/diagnostic_log.h"

namespace bugg {
namespace {
bool retryable_response(int status, bool interrupted) {
  return interrupted || status == 0 || status == 408 || status == 429 || status >= 500;
}
}  // namespace
QList<QUrl> resource_urls(const QUrl& official, const QStringList& source_order,
                          const QUrl& bugg_base) {
  const auto capability =
      official.host() == "api.curseforge.com" ? SourceCapability::CurseForgeContent
      : official.host() == "api.modrinth.com" ? SourceCapability::ModrinthContent
                                              : SourceCapability::GameResources;
  const auto plan = resolve_sources(source_order, capability);
  if (!plan.error.isEmpty()) throw std::runtime_error(plan.error.toUtf8().constData());
  if (!official.isValid() || !official.userInfo().isEmpty() ||
      (official.scheme() != "https" && official.scheme() != "http"))
    throw std::runtime_error(QCoreApplication::translate("Bugg", "资源 URL 无效").toStdString());
  const auto host = official.host().toLower();
  const auto path = official.path();
  const bool metadata = host == "api.curseforge.com" || host == "api.modrinth.com";
  QString bugg_path;
  QString bmcl_path;
  if (host == "api.curseforge.com" && path.startsWith("/v1/"))
    bugg_path = "/v1/catalog/curseforge" + path.mid(3);
  else if (host == "api.modrinth.com" && path.startsWith("/v2/"))
    bugg_path = "/v1/catalog/modrinth" + path.mid(3);
  else if ((host == "piston-meta.mojang.com" || host == "launchermeta.mojang.com" ||
            host == "piston-data.mojang.com" || host == "launcher.mojang.com") &&
           (path.startsWith("/mc/") || path.startsWith("/v1/")))
    bugg_path = bmcl_path = path;
  else if (host == "resources.download.minecraft.net")
    bugg_path = bmcl_path = "/assets" + path;
  else if (host == "libraries.minecraft.net" || host == "maven.minecraftforge.net")
    bugg_path = bmcl_path = "/maven" + path;
  else if (host == "meta.fabricmc.net")
    bugg_path = bmcl_path = "/fabric-meta" + path;
  else if (host == "meta.quiltmc.org")
    bugg_path = bmcl_path = "/quilt-meta" + path;
  else if (host == "maven.fabricmc.net") {
    bugg_path = "/fabric-maven" + path;
    bmcl_path = "/maven" + path;
  } else if (host == "maven.quiltmc.org" && path.startsWith("/repository/release/")) {
    bugg_path = "/quilt-maven" + path;
    bmcl_path = "/maven/" + path.mid(QString("/repository/release/").size());
  } else if (host == "maven.neoforged.net" && path.startsWith("/releases/")) {
    bugg_path = "/neoforge-maven" + path;
    bmcl_path = "/maven/" + path.mid(QString("/releases/").size());
  } else if (host == "cdn.modrinth.com" && path.startsWith("/data/")) {
    bugg_path = "/mods/modrinth" + path;
  } else if ((host == "edge.forgecdn.net" || host == "mediafilez.forgecdn.net") &&
             path.startsWith("/files/")) {
    bugg_path =
        (host == "edge.forgecdn.net" ? "/mods/curseforge" : "/mods/curseforge-mediafilez") + path;
  }
  QList<QUrl> result;
  for (const auto& route : plan.routes) {
    const auto& source = route.actual;
    QUrl url = official;
    if (source == "BUGG" && metadata && !bugg_path.isEmpty()) {
      url = source_url("BUGG", bugg_path, bugg_base);
      url.setQuery(official.query());
    } else if (official.hasQuery() || official.hasFragment()) {
      // 元数据的动态 query 不伪装成镜像静态资源。
      if (source != "官方") continue;
    } else if (source == "BUGG" && !bugg_path.isEmpty())
      url = source_url("BUGG", bugg_path, bugg_base);
    else if (source == "BMCLAPI" && !bmcl_path.isEmpty())
      url = source_url("BMCLAPI", bmcl_path, bugg_base);
    else if (source != "官方")
      continue;
    if (!result.contains(url)) result.append(url);
    // The publisher's two CDNs can differ in availability for the same file.
    // Keep the selected source and metadata path/hash; never invent a new file.
    if (!official.hasQuery() &&
        (host == "edge.forgecdn.net" || host == "mediafilez.forgecdn.net")) {
      auto alternate = url;
      if (source == "BUGG")
        alternate = source_url(
            "BUGG",
            (host == "edge.forgecdn.net" ? "/mods/curseforge-mediafilez" : "/mods/curseforge") +
                path,
            bugg_base);
      else if (source == "官方")
        alternate.setHost(host == "edge.forgecdn.net" ? "mediafilez.forgecdn.net"
                                                      : "edge.forgecdn.net");
      if (!result.contains(alternate)) result.append(alternate);
    }
  }
  if (result.isEmpty()) result.append(official);
  return result;
}
ResourceClient::ResourceClient(QStringList source_order, Cancellation cancelled, Progress progress,
                               HttpClient* transport, int concurrency, QUrl bugg_base)
    : source_order_(std::move(source_order)),
      bugg_base_(std::move(bugg_base)),
      cancelled_(std::move(cancelled)),
      progress_(std::move(progress)),
      transport_(transport ? transport : &http_),
      concurrency_(qBound(1, concurrency, 32)) {
  clock_.start();
  health_connection_ =
      QObject::connect(transport_, &HttpClient::unreachable, &http_, [this](const QUrl& url) {
        unavailable_until_[url.adjusted(QUrl::RemovePath | QUrl::RemoveQuery |
                                        QUrl::RemoveFragment)] = clock_.elapsed() + 60000;
      });
}
ResourceClient::~ResourceClient() { QObject::disconnect(health_connection_); }
bool ResourceClient::cooling_down(const QUrl& url) const {
  return unavailable_until_.value(
             url.adjusted(QUrl::RemovePath | QUrl::RemoveQuery | QUrl::RemoveFragment), 0) >
         clock_.elapsed();
}

QJsonObject ResourceClient::json(const QUrl& official, const QJsonObject& body) {
  return json_many({official}, body).value(official);
}

QHash<QUrl, QJsonObject> ResourceClient::json_many(const QList<QUrl>& official,
                                                   const QJsonObject& body) {
  struct Pending {
    QUrl original;
    QList<QUrl> urls;
    int candidate = 0;
    int retries = 0;
    qint64 ready_at = 0;
  };
  QList<Pending> queue;
  QSet<QUrl> unique;
  for (const auto& url : official) {
    if (unique.contains(url)) continue;
    unique.insert(url);
    auto urls = resource_urls(url, source_order_, bugg_base_);
    if (qEnvironmentVariableIsEmpty("BUGGCRAFT_CURSEFORGE_API_KEY"))
      urls.removeIf([](const QUrl& candidate) { return candidate.host() == "api.curseforge.com"; });
    if (urls.isEmpty())
      throw std::runtime_error(QCoreApplication::translate(
                                   "Bugg", "CurseForge 授权不可用，请在源站后台配置 API 密钥后重试")
                                   .toUtf8()
                                   .constData());
    queue.append({url, urls});
  }
  QHash<QUrl, QJsonObject> result;
  if (queue.isEmpty()) return result;
  const auto total = queue.size();
  QElapsedTimer metadata_clock;
  metadata_clock.start();
  qint64 metadata_published_at = 0;
  progress_(-1, QCoreApplication::translate("Bugg", "获取资源信息 0 / %1").arg(total));
  QHash<quint64, Pending> active;
  QEventLoop loop;
  QTimer timer;
  QSet<quint64> transient;
  const auto transient_connection =
      QObject::connect(transport_, &HttpClient::transient_failure, &loop, [&](quint64 id) {
        if (active.contains(id)) transient.insert(id);
      });
  QString error;
  std::function<void()> pump;
  pump = [&] {
    if (cancelled_->load() || !error.isEmpty()) {
      loop.quit();
      return;
    }
    while (!queue.isEmpty() && active.size() < concurrency_) {
      const auto next = std::find_if(queue.begin(), queue.end(), [](const Pending& item) {
        return item.ready_at <= QDateTime::currentMSecsSinceEpoch();
      });
      if (next == queue.end()) break;
      auto item = *next;
      queue.erase(next);
      while (item.candidate + 1 < item.urls.size() && cooling_down(item.urls[item.candidate]))
        ++item.candidate;
      HttpRequest request;
      request.url = item.urls[item.candidate];
      if (!body.isEmpty()) {
        request.method = "POST";
        request.body = QJsonDocument(body).toJson(QJsonDocument::Compact);
        request.headers["Content-Type"] = "application/json";
      }
      if (request.url.host() == "api.curseforge.com")
        request.headers["x-api-key"] = qgetenv("BUGGCRAFT_CURSEFORGE_API_KEY");
      active.insert(transport_->request(request), item);
    }
    if (active.isEmpty() && queue.isEmpty()) loop.quit();
  };
  const auto connection = QObject::connect(
      transport_, &HttpClient::response, &loop,
      [&](quint64 id, const QByteArray& bytes, const QString& failure, int status) {
        if (!active.contains(id)) return;
        auto item = active.take(id);
        const bool interrupted = transient.remove(id);
        QJsonParseError parse;
        const auto document = QJsonDocument::fromJson(bytes, &parse);
        const auto object = document.object();
        const bool missing_key = object.value("code") == "catalog_authorization_unavailable";
        if (failure.isEmpty() && parse.error == QJsonParseError::NoError && document.isObject()) {
          result.insert(item.original, object);
        } else if (!missing_key && retryable_response(status, interrupted) && item.retries < 6) {
          ++item.retries;
          if (item.candidate + 1 < item.urls.size()) ++item.candidate;
          item.ready_at = QDateTime::currentMSecsSinceEpoch() + qMin(8000, 250 << item.retries);
          queue.append(item);
        } else if (item.retries < 6 && ++item.candidate < item.urls.size()) {
          ++item.retries;
          queue.append(item);
        } else {
          error = missing_key || (item.original.host() == "api.curseforge.com" &&
                                  (status == 401 || status == 403))
                      ? QCoreApplication::translate(
                            "Bugg", "CurseForge 授权不可用，请在源站后台配置 API 密钥后重试")
                  : status == 429
                      ? QCoreApplication::translate("Bugg", "资源目录请求过于频繁，请稍后重试")
                  : status == 404 ? QCoreApplication::translate("Bugg", "资源文件已下架或不存在")
                  : failure.isEmpty() ? QCoreApplication::translate("Bugg", "资源元数据格式错误")
                                      : failure;
        }
        pump();
      });
  QObject::connect(&timer, &QTimer::timeout, &loop, [&] {
    pump();
    const auto elapsed = metadata_clock.elapsed();
    if (!cancelled_->load() && error.isEmpty() && result.size() < total &&
        elapsed - metadata_published_at >= 500) {
      metadata_published_at = elapsed;
      progress_(-1, QCoreApplication::translate("Bugg", "获取资源信息 %1 / %2 · 已等待 %3 秒")
                        .arg(result.size())
                        .arg(total)
                        .arg(elapsed / 1000));
    }
  });
  timer.start(50);
  pump();
  if (!active.isEmpty() || !queue.isEmpty()) loop.exec();
  QObject::disconnect(connection);
  QObject::disconnect(transient_connection);
  for (const auto id : active.keys()) transport_->cancel(id);
  check_cancelled(cancelled_);
  if (!error.isEmpty())
    throw std::runtime_error(
        (QCoreApplication::translate("Bugg", "获取元数据失败：") + error).toUtf8().constData());
  return result;
}

QHash<QString, QString> ResourceClient::fetch(const QList<GameResource>& resources,
                                              bool continue_on_error) {
  record_diagnostic("download.batch",
                    {{"files", resources.size()},
                     {"per_group_concurrency", concurrency_},
                     {"bugg_origin", diagnostic_url(bugg_base_)},
                     {"source_order", QJsonArray::fromStringList(source_order_)}});
  struct Pending {
    GameResource resource;
    QList<QUrl> urls;
    int attempt = 0;
    int retries = 0;
    QString group;
    qint64 received = 0;
    qint64 started = 0;
    qint64 ready_at = 0;
  };
  QList<Pending> queue;
  QHash<QString, GameResource> paths;
  QElapsedTimer verification_clock;
  verification_clock.start();
  int checked = 0;
  progress_(0, QCoreApplication::translate("Bugg", "校验文件 0 / %1").arg(resources.size()));
  for (const auto& resource : resources) {
    check_cancelled(cancelled_);
    ++checked;
    if (paths.contains(resource.path)) {
      if (paths.value(resource.path).sha1 != resource.sha1)
        throw std::runtime_error(
            QCoreApplication::translate("Bugg", "同一路径存在冲突的依赖摘要").toStdString());
      continue;
    }
    paths.insert(resource.path, resource);
    if (!valid_file(resource.path, resource.sha1, resource.size, cancelled_)) {
      auto urls = resource_urls(resource.url, source_order_, bugg_base_);
      for (const auto& alternative : resource.alternatives)
        for (const auto& url : resource_urls(alternative, source_order_, bugg_base_))
          if (!urls.contains(url)) urls.append(url);
      QString group = resource.group;
      const auto path = QDir::fromNativeSeparators(resource.path).toLower();
      if (group.isEmpty()) {
        for (const auto& name : {"assets", "libraries", "resourcepacks", "shaderpacks", "mods",
                                 "datapacks", "runtime", "installers", "versions"})
          if (path.contains('/' + QString(name) + '/')) {
            group = name;
            break;
          }
      }
      if (group.isEmpty()) group = "files";
      Pending pending{resource, urls};
      pending.group = group;
      queue.append(pending);
    }
    if (checked == resources.size() || verification_clock.elapsed() >= 100) {
      verification_clock.restart();
      progress_(double(checked) / resources.size(),
                QCoreApplication::translate("Bugg", "校验文件 %1 / %2 · %3")
                    .arg(checked)
                    .arg(resources.size())
                    .arg(QFileInfo(resource.path).fileName()));
    }
  }
  if (queue.isEmpty()) {
    progress_(1, QCoreApplication::translate("Bugg", "文件已校验"));
    return {};
  }
  const int total = queue.size();
  int done = 0;
  QHash<quint64, Pending> active;
  QHash<QString, int> group_active;
  QHash<quint64, double> partial;
  QEventLoop loop;
  QTimer cancel_timer;
  QSet<quint64> transient;
  const auto transient_connection =
      QObject::connect(transport_, &HttpClient::transient_failure, &loop, [&](quint64 id) {
        if (active.contains(id)) transient.insert(id);
      });
  QElapsedTimer throttle;
  throttle.start();
  QElapsedTimer transfer_clock;
  transfer_clock.start();
  qint64 received_bytes = 0, sampled_bytes = 0, sampled_at = 0;
  double speed = 0;
  QHash<QString, QString> failures;
  QString error;
  // One publisher owns this batch. Bound periodic updates, but flush phase
  // transitions immediately so a fast cached phase never masks a slow wait.
  const auto publish = [&](const QString& detail, bool immediate = false) {
    if (!immediate && throttle.elapsed() < 100) return;
    throttle.restart();
    double fraction = done;
    for (auto value : partial) fraction += value;
    progress_(fraction / total, QCoreApplication::translate("Bugg", "下载文件 %1 / %2 · %3")
                                    .arg(done)
                                    .arg(total)
                                    .arg(detail));
  };
  const auto snapshot = [&](const Pending& pending, const QString& state, const QString& detail) {
    if (!transfer_progress_) return;
    const auto elapsed = transfer_clock.elapsed();
    const auto file_speed =
        pending.received * 1000.0 / qMax<qint64>(100, elapsed - pending.started);
    const QLocale locale;
    transfer_progress_(
        {{"path", pending.resource.path},
         {"state", state},
         {"progress",
          pending.resource.size > 0 ? double(pending.received) / pending.resource.size : -1},
         {"received", pending.received},
         {"total", pending.resource.size},
         {"speedText", locale.formattedDataSize(qint64(file_speed)) + "/s"},
         {"aggregateSpeedText", locale.formattedDataSize(qint64(speed)) + "/s"},
         {"activeTransfers", active.size()},
         {"transferText",
          locale.formattedDataSize(pending.received) + " / " +
              (pending.resource.size > 0 ? locale.formattedDataSize(pending.resource.size)
                                         : QString("—"))},
         {"detail", detail}});
  };
  std::function<void()> pump;
  pump = [&] {
    if (cancelled_->load() || !error.isEmpty()) {
      loop.quit();
      return;
    }
    while (!queue.isEmpty()) {
      const auto next = std::find_if(queue.begin(), queue.end(), [&](const Pending& item) {
        return active.size() < concurrency_ && group_active.value(item.group) < concurrency_ &&
               item.ready_at <= QDateTime::currentMSecsSinceEpoch();
      });
      if (next == queue.end()) break;
      auto pending = *next;
      queue.erase(next);
      while (pending.attempt + 1 < pending.urls.size() &&
             cooling_down(pending.urls[pending.attempt]))
        ++pending.attempt;
      HttpRequest request;
      request.url = pending.urls[pending.attempt++];
      request.output_path = pending.resource.path;
      request.sha1 = pending.resource.sha1;
      request.resume = true;
      request.expected_size = pending.resource.size;
      request.maximum_bytes =
          request.expected_size >= 0 ? request.expected_size + 1 : 1024LL * 1024 * 1024;
      request.total_ms = 10 * 60 * 1000;
      request.first_byte_ms = 60000;
      record_diagnostic("download.attempt",
                        {{"file", QFileInfo(pending.resource.path).fileName()},
                         {"publisher_url", diagnostic_url(pending.resource.url)},
                         {"request_url", diagnostic_url(request.url)},
                         {"candidate", pending.attempt},
                         {"retry", pending.retries},
                         {"group", pending.group}});
      pending.received = 0;
      pending.started = transfer_clock.elapsed();
      const auto id = transport_->request(request);
      active.insert(id, pending);
      ++group_active[pending.group];
      snapshot(pending, "downloading", QCoreApplication::translate("Bugg", "连接中"));
    }
    if (active.isEmpty() && queue.isEmpty()) loop.quit();
  };
  const auto complete = QObject::connect(
      transport_, &HttpClient::response, &loop,
      [&](quint64 id, const QByteArray&, const QString& failure, int status) {
        if (!active.contains(id)) return;
        auto pending = active.take(id);
        const bool interrupted = transient.remove(id);
        --group_active[pending.group];
        partial.remove(id);
        if (failure.isEmpty()) {
          pending.received = pending.resource.size > 0 ? pending.resource.size : pending.received;
          ++done;
          snapshot(pending, "checking",
                   QCoreApplication::translate("Bugg", "下载完成，待校验安装"));
        } else if (retryable_response(status, interrupted) && pending.retries < 6) {
          snapshot(pending, "downloading",
                   QCoreApplication::translate("Bugg", "连接中断，自动重试"));
          ++pending.retries;
          // Try the next allowed route before waiting on the same broken link.
          // The final route still gets bounded retries for transient outages.
          if (!interrupted || pending.attempt >= pending.urls.size()) --pending.attempt;
          pending.ready_at =
              QDateTime::currentMSecsSinceEpoch() + qMin(8000, 250 << pending.retries);
          queue.append(pending);
        } else if (pending.retries < 6 && pending.attempt < pending.urls.size()) {
          ++pending.retries;
          queue.append(pending);
        } else {
          error = QFileInfo(pending.resource.path).fileName() + "：" + failure;
          failures[pending.resource.path] = error;
          snapshot(pending, "failed", error);
          if (continue_on_error) {
            ++done;
            error.clear();
          }
        }
        publish(failure.isEmpty()
                    ? QFileInfo(pending.resource.path).fileName()
                    : QCoreApplication::translate("Bugg", "连接中断，正在尝试其他来源或自动重试"),
                done == total || !failure.isEmpty());
        pump();
      });
  const auto progress = QObject::connect(
      transport_, &HttpClient::progress, &loop, [&](quint64 id, qint64 received, qint64 size) {
        if (!active.contains(id)) return;
        auto& pending = active[id];
        received_bytes += qMax<qint64>(0, received - pending.received);
        pending.received = received;
        const auto elapsed = transfer_clock.elapsed();
        if (elapsed - sampled_at >= 200) {
          speed = (received_bytes - sampled_bytes) * 1000.0 / (elapsed - sampled_at);
          sampled_bytes = received_bytes;
          sampled_at = elapsed;
        }
        partial[id] = size > 0 ? qBound(0.0, double(received) / size, 1.0) : 0.0;
        if (throttle.elapsed() < 100) return;
        publish(QFileInfo(pending.resource.path).fileName() + " · " +
                QLocale().formattedDataSize(pending.received) + " / " +
                (size > 0 ? QLocale().formattedDataSize(size) : QString("—")) + " · " +
                QLocale().formattedDataSize(qint64(speed)) + "/s");
        snapshot(pending, "downloading", QCoreApplication::translate("Bugg", "下载中"));
      });
  const auto resumed =
      QObject::connect(transport_, &HttpClient::resumed, &loop, [&](quint64 id, qint64 bytes) {
        if (!active.contains(id)) return;
        auto& pending = active[id];
        pending.received = bytes;
        partial[id] = pending.resource.size > 0 ? double(bytes) / pending.resource.size : 0;
        snapshot(pending, "downloading", QCoreApplication::translate("Bugg", "继续未完成的下载"));
      });
  QObject::connect(&cancel_timer, &QTimer::timeout, &loop, [&] {
    pump();
    if (!cancelled_->load() && error.isEmpty() && done < total && throttle.elapsed() >= 500)
      publish(active.isEmpty()
                  ? QCoreApplication::translate("Bugg", "等待自动重试")
                  : QCoreApplication::translate("Bugg", "%1 个连接 · 等待数据 · 已用 %2 秒")
                        .arg(active.size())
                        .arg(transfer_clock.elapsed() / 1000));
  });
  cancel_timer.start(50);
  publish(QCoreApplication::translate("Bugg", "正在连接下载源"), true);
  pump();
  if (!active.isEmpty() || !queue.isEmpty()) loop.exec();
  QObject::disconnect(complete);
  QObject::disconnect(transient_connection);
  QObject::disconnect(resumed);
  QObject::disconnect(progress);
  for (auto id : active.keys()) transport_->cancel(id);
  check_cancelled(cancelled_);
  if (!error.isEmpty()) throw std::runtime_error(error.toUtf8().constData());
  return failures;
}
}  // namespace bugg
