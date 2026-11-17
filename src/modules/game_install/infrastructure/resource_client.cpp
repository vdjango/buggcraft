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
#include "modules/game_install/infrastructure/resource_source_provider.h"
#include "platform/diagnostics/diagnostic_log.h"

namespace bugg {
namespace {
bool retryable_response(int status, bool interrupted) {
  return status != 429 && (interrupted || status == 0 || status == 408 || status >= 500);
}

QUrl request_origin(const QUrl& url) {
  return url.adjusted(QUrl::RemovePath | QUrl::RemoveQuery | QUrl::RemoveFragment);
}

QString source_label(const QUrl& url, const QUrl& bugg_base) {
  const auto host = url.host().toLower();
  if (host == bugg_base.host().toLower() && url.port() == bugg_base.port()) return "BUGG";
  if (host.endsWith(".bugg.icu") || host == "bugg.icu") return "BUGG";
  if (host.contains("modrinth")) return "Modrinth";
  if (host.contains("forgecdn") || host.contains("curseforge")) return "CurseForge";
  if (host.contains("bmclapi")) return "BMCLAPI";
  if (host.contains("mojang") || host.contains("minecraft")) return "官方";
  return host;
}
}  // namespace
QList<QUrl> resource_urls(const QUrl& official, const QStringList& source_order,
                          const QUrl& bugg_base) {
  if (!official.isValid() || !official.userInfo().isEmpty() ||
      (official.scheme() != "https" && official.scheme() != "http"))
    throw std::runtime_error("Invalid resource URL");
  const auto host = official.host().toLower();
  const auto capability = host == "api.curseforge.com"     ? SourceCapability::CurseForgeMetadata
                          : host.endsWith(".forgecdn.net") ? SourceCapability::CurseForgeContent
                          : host == "api.modrinth.com" || host == "cdn.modrinth.com"
                              ? SourceCapability::ModrinthContent
                              : SourceCapability::GameResources;
  const auto plan = resolve_sources(source_order, capability);
  if (!plan.error.isEmpty()) throw std::runtime_error(plan.error.toUtf8().constData());
  QList<QUrl> result;
  for (const auto& route : plan.routes) {
    const auto* provider = resource_source_provider(route.actual);
    if (!provider) continue;
    for (const auto& url : provider->urls(official, bugg_base))
      if (!result.contains(url)) result.append(url);
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
      http_(nullptr, {}, 64),
      transport_(transport ? transport : &http_),
      concurrency_(qBound(1, concurrency, 32)) {}
ResourceClient::~ResourceClient() = default;

QJsonObject ResourceClient::json(const QUrl& official, const QJsonObject& body) {
  return json(official, body, 45000, 6);
}
QJsonObject ResourceClient::json(const QUrl& official, const QJsonObject& body, int budget_ms,
                                 int retries) {
  return json_many({official}, body, budget_ms, retries).value(official);
}

QHash<QUrl, QJsonObject> ResourceClient::json_many(const QList<QUrl>& official,
                                                   const QJsonObject& body) {
  return json_many(official, body, 45000, 6);
}
QHash<QUrl, QJsonObject> ResourceClient::json_many(const QList<QUrl>& official,
                                                   const QJsonObject& body, int budget_ms,
                                                   int retries, Progress batch_progress,
                                                   bool continue_on_error) {
  struct Pending {
    QUrl original;
    QList<QUrl> urls;
    int candidate = 0;
    int retries = 0;
    qint64 ready_at = 0;
    QUrl route;
  };
  QList<Pending> queue;
  QSet<QUrl> failed_origins;
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
  if (!batch_progress)
    progress_(-1, QCoreApplication::translate("Bugg", "获取资源信息 0 / %1").arg(total));
  QHash<quint64, Pending> active;
  QEventLoop loop;
  QTimer timer;
  const auto health_connection =
      QObject::connect(transport_, &HttpClient::unreachable, &loop,
                       [&](const QUrl& url) { failed_origins.insert(request_origin(url)); });
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
    if (continue_on_error && metadata_clock.elapsed() >= qBound(1, budget_ms, 45000)) {
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
      while (item.candidate + 1 < item.urls.size() &&
             failed_origins.contains(request_origin(item.urls[item.candidate])))
        ++item.candidate;
      HttpRequest request;
      request.url = item.urls[item.candidate];
      item.route = request.url;
      request.total_ms = qBound(1, budget_ms, 45000);
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
        } else if (!missing_key && retryable_response(status, interrupted) &&
                   item.retries < retries) {
          ++item.retries;
          if (status != 429) failed_origins.insert(request_origin(item.route));
          const bool has_next_route = item.candidate + 1 < item.urls.size();
          if (has_next_route) ++item.candidate;
          item.ready_at = 0;
          queue.append(item);
        } else if (item.retries < retries && ++item.candidate < item.urls.size()) {
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
          if (continue_on_error) error.clear();
        }
        pump();
      });
  QObject::connect(&timer, &QTimer::timeout, &loop, [&] {
    pump();
    const auto elapsed = metadata_clock.elapsed();
    if (!cancelled_->load() && error.isEmpty() && result.size() < total &&
        elapsed - metadata_published_at >= 500) {
      metadata_published_at = elapsed;
      (batch_progress ? batch_progress : progress_)(
          batch_progress ? double(result.size()) / total : -1,
          QCoreApplication::translate("Bugg", "获取资源信息 %1 / %2 · 已等待 %3 秒")
              .arg(result.size())
              .arg(total)
              .arg(elapsed / 1000));
    }
  });
  timer.start(50);
  pump();
  if (!active.isEmpty() || !queue.isEmpty()) loop.exec();
  QObject::disconnect(connection);
  QObject::disconnect(health_connection);
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
  return fetch(resources, continue_on_error, {});
}
QHash<QString, QString> ResourceClient::fetch(
    const QList<GameResource>& resources, bool continue_on_error,
    const std::function<QList<GameResource>(const GameResource&)>& expand,
    Progress batch_progress) {
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
    QUrl route;
    QString source;
  };
  QList<Pending> queue;
  QSet<QUrl> failed_origins;
  QHash<QString, GameResource> paths;
  QElapsedTimer verification_clock;
  verification_clock.start();
  int total = 0;
  if (!batch_progress)
    progress_(0, QCoreApplication::translate("Bugg", "校验文件 0 / %1").arg(resources.size()));
  const auto enqueue = [&](const QList<GameResource>& additions) {
    auto discovered = additions;
    for (qsizetype position = 0; position < discovered.size(); ++position) {
      const auto resource = discovered[position];
      check_cancelled(cancelled_);
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
        if (QStringList{"mods", "resourcepacks", "shaderpacks", "datapacks"}.contains(group))
          group = "content";
        Pending pending{resource, urls};
        pending.group = group;
        queue.append(pending);
        ++total;
      } else if (expand) {
        discovered.append(expand(resource));
      }
      if (!batch_progress &&
          (position + 1 == discovered.size() || verification_clock.elapsed() >= 100)) {
        verification_clock.restart();
        const auto known = paths.size() + discovered.size() - position - 1;
        progress_(double(paths.size()) / qMax<qsizetype>(1, known),
                  QCoreApplication::translate("Bugg", "校验文件 %1 / %2 · %3")
                      .arg(paths.size())
                      .arg(known)
                      .arg(QFileInfo(resource.path).fileName()));
      }
    }
  };
  enqueue(resources);
  if (queue.isEmpty()) {
    if (batch_progress)
      batch_progress(1, QCoreApplication::translate("Bugg", "文件已校验"));
    else
      progress_(1, QCoreApplication::translate("Bugg", "文件已校验"));
    return {};
  }
  int done = 0, successful = 0;
  QHash<quint64, Pending> active;
  QHash<QString, int> group_active;
  QHash<quint64, double> partial;
  QEventLoop loop;
  QTimer cancel_timer;
  const auto health_connection =
      QObject::connect(transport_, &HttpClient::unreachable, &loop,
                       [&](const QUrl& url) { failed_origins.insert(request_origin(url)); });
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
  const auto notify_progress = [&](const auto& callback) {
    try {
      callback();
    } catch (const std::exception& exception) {
      error = QString::fromUtf8(exception.what());
      loop.quit();
    }
  };
  // One publisher owns this batch. Bound periodic updates, but flush phase
  // transitions immediately so a fast cached phase never masks a slow wait.
  const auto publish = [&](const QString& detail, bool immediate = false) {
    if (!immediate && throttle.elapsed() < 100) return;
    throttle.restart();
    double fraction = batch_progress ? successful : done;
    for (auto value : partial) fraction += value;
    QStringList sources;
    for (const auto& item : active) {
      const auto name = item.source;
      if (!name.isEmpty() && !sources.contains(name)) sources.append(name);
    }
    sources.sort();
    notify_progress([&] {
      (batch_progress ? batch_progress : progress_)(
          fraction / total,
          QCoreApplication::translate("Bugg", "下载文件 %1 / %2 · %3")
                  .arg(done)
                  .arg(total)
                  .arg(detail) +
              (sources.isEmpty()
                   ? QString{}
                   : QCoreApplication::translate("Bugg", " · 来源：%1").arg(sources.join(" / "))));
    });
  };
  const auto snapshot = [&](const Pending& pending, const QString& state, const QString& detail) {
    if (!transfer_progress_) return;
    const auto elapsed = transfer_clock.elapsed();
    const auto file_speed =
        pending.received * 1000.0 / qMax<qint64>(100, elapsed - pending.started);
    const QLocale locale;
    notify_progress([&] {
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
           {"source", pending.source},
           {"transferText",
            locale.formattedDataSize(pending.received) + " / " +
                (pending.resource.size > 0 ? locale.formattedDataSize(pending.resource.size)
                                           : QString("—"))},
           {"detail", detail}});
    });
  };
  const auto route_connection = QObject::connect(
      transport_, &HttpClient::route_changed, &loop, [&](quint64 id, const QUrl& url) {
        if (!active.contains(id)) return;
        active[id].route = url;
        const auto routed_source = source_label(url, bugg_base_);
        if (QStringList{"BUGG", "Modrinth", "CurseForge", "BMCLAPI", "官方"}.contains(
                routed_source))
          active[id].source = routed_source;
        snapshot(active[id], "downloading", QCoreApplication::translate("Bugg", "连接中"));
        publish(QFileInfo(active[id].resource.path).fileName(), true);
      });
  std::function<void()> pump;
  pump = [&] {
    if (cancelled_->load() || !error.isEmpty()) {
      loop.quit();
      return;
    }
    while (!queue.isEmpty() && !cancelled_->load() && error.isEmpty()) {
      const auto next = std::find_if(queue.begin(), queue.end(), [&](const Pending& item) {
        return group_active.value(item.group) < concurrency_ &&
               item.ready_at <= QDateTime::currentMSecsSinceEpoch();
      });
      if (next == queue.end()) break;
      auto pending = *next;
      queue.erase(next);
      while (pending.attempt + 1 < pending.urls.size() &&
             failed_origins.contains(request_origin(pending.urls[pending.attempt])))
        ++pending.attempt;
      HttpRequest request;
      request.url = pending.urls[pending.attempt++];
      pending.route = request.url;
      pending.source = source_label(request.url, bugg_base_);
      request.output_path = pending.resource.path;
      request.sha1 = pending.resource.sha1;
      request.resume = true;
      const auto competing_files = qMin<qsizetype>(concurrency_, active.size() + queue.size() + 1);
      request.range_connections = qBound(2, int(64 / competing_files), 64);
      // CF large-file tests show HTTP/2 multiplexing shares a slow TCP path.
      // Restrict this policy to the measured publisher; metadata keeps HTTP/2.
      const auto publisher = pending.resource.url.host().toLower();
      request.http2_allowed = !publisher.endsWith(".forgecdn.net");
      // Other measured publishers are faster as a single HTTP/2 transfer.
      // BMCLAPI also assigns distribution nodes that may refuse byte ranges.
      request.parallel_ranges = publisher.endsWith(".forgecdn.net");
      request.expected_size = pending.resource.size;
      request.maximum_bytes =
          request.expected_size >= 0 ? request.expected_size + 1 : 1024LL * 1024 * 1024;
      request.total_ms = 10 * 60 * 1000;
      request.first_byte_ms = 15000;
      if (pending.attempt < pending.urls.size())
        request.minimum_bytes_per_second =
            pending.resource.size >= 8 * 1024 * 1024 ? 128 * 1024 : 4096;
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
          ++successful;
          snapshot(pending, "checking",
                   QCoreApplication::translate("Bugg", "下载完成，待校验安装"));
          if (expand) {
            try {
              enqueue(expand(pending.resource));
            } catch (const std::exception& exception) {
              error = QString::fromUtf8(exception.what());
            }
          }
        } else if (retryable_response(status, interrupted) && pending.retries < 6) {
          if (status != 429) failed_origins.insert(request_origin(pending.route));
          snapshot(pending, "downloading",
                   QCoreApplication::translate("Bugg", "连接中断，自动重试"));
          ++pending.retries;
          // Try the next allowed route before waiting on the same broken link.
          // The final route still gets bounded retries for transient outages.
          const bool has_next_route = pending.attempt < pending.urls.size();
          if (!has_next_route) --pending.attempt;
          pending.ready_at = 0;
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
                  : QCoreApplication::translate("Bugg", "%1 个文件传输 · 等待数据 · 已用 %2 秒")
                        .arg(active.size())
                        .arg(transfer_clock.elapsed() / 1000));
  });
  cancel_timer.start(50);
  publish(QCoreApplication::translate("Bugg", "正在连接下载源"), true);
  pump();
  if (!active.isEmpty() || !queue.isEmpty()) loop.exec();
  QObject::disconnect(complete);
  QObject::disconnect(health_connection);
  QObject::disconnect(transient_connection);
  QObject::disconnect(resumed);
  QObject::disconnect(route_connection);
  QObject::disconnect(progress);
  for (auto id : active.keys()) transport_->cancel(id);
  check_cancelled(cancelled_);
  if (!error.isEmpty()) throw std::runtime_error(error.toUtf8().constData());
  return failures;
}
}  // namespace bugg
