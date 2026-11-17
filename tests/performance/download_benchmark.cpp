// Explicit large-file transport experiment; uses the production HttpClient.
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkProxy>
#include <QSaveFile>
#include <QTimer>
#include <QtConcurrentRun>

#include "modules/game_install/infrastructure/resource_client.h"
#include "platform/diagnostics/diagnostic_log.h"
#include "platform/http/http_client.h"

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  // Keep explicit process/environment HTTP proxies out of the experiment.
  // A system-wide tunnel is outside this process's ability to rule out.
  QNetworkProxy::setApplicationProxy(QNetworkProxy::NoProxy);
  const auto args = app.arguments();
  if (args.size() != 4) {
    qCritical("Usage: download_benchmark manifest.json report.json output-directory");
    return 2;
  }
  QFile input(args[1]);
  if (!input.open(QIODevice::ReadOnly)) return 2;
  const auto manifest = QJsonDocument::fromJson(input.readAll()).object();
  if (!QDir().mkpath(args[3])) return 2;
  int failures = 0;
  const auto started_utc = QDateTime::currentDateTimeUtc().toString(Qt::ISODate);
  QFutureWatcher<void> watcher;
  QObject::connect(&watcher, &QFutureWatcher<void>::finished, &app, &QCoreApplication::quit);
  watcher.setFuture(QtConcurrent::run([&] {
    QJsonArray measurements;
    const auto save = [&] {
      QSaveFile report(args[2]);
      if (!report.open(QIODevice::WriteOnly)) return false;
      const auto bytes =
          QJsonDocument(QJsonObject{{"qt", qVersion()},
                                    {"started_utc", started_utc},
                                    {"proxy", "NoProxy; system-wide tunnels not detected"},
                                    {"measurements", measurements}})
              .toJson();
      return report.write(bytes) == bytes.size() && report.commit();
    };
    for (const auto& value : manifest["cases"].toArray()) {
      const auto row = value.toObject();
      const auto name = row["name"].toString();
      if (row["files"].isArray()) {
        QList<bugg::GameResource> files;
        qint64 bytes = 0;
        for (const auto& file_value : row["files"].toArray()) {
          const auto file = file_value.toObject();
          const QUrl url(file["url"].toString());
          const auto size = file["size"].toInteger();
          const auto sha1 = file["sha1"].toString().toLatin1();
          if (url.scheme() != "https" || url.hasQuery() || size < 1 || sha1.size() != 40) {
            files.clear();
            break;
          }
          const auto target = args[3] + '/' + name + '/' + QString::number(files.size());
          if (QFileInfo::exists(target)) {
            files.clear();
            break;
          }
          bytes += size;
          files.append({url, target, sha1, size, {}, file["category"].toString()});
        }
        if (files.isEmpty() || bytes > qint64(4) * 1024 * 1024 * 1024) {
          ++failures;
          break;
        }
        const auto cancelled = std::make_shared<std::atomic_bool>(false);
        bugg::HttpClient http(nullptr, {20000, 600000}, row["pool"].toInt(64));
        QStringList order;
        for (const auto& source : row["source_order"].toArray()) order.append(source.toString());
        if (order.isEmpty()) order = bugg::supported_download_sources();
        bugg::ResourceClient resources(
            order, cancelled, [](double, const QString&) {}, &http, row["concurrency"].toInt(6));
        QElapsedTimer clock;
        QTimer sample, deadline;
        deadline.setSingleShot(true);
        QHash<QString, qint64> received;
        QJsonArray samples;
        QString error;
        bool observation_only = false;
        const auto observe = [&] {
          qint64 total = 0;
          for (const auto value : received) total += value;
          samples.append(QJsonObject{{"ms", clock.elapsed()}, {"bytes", total}});
        };
        resources.set_transfer_progress([&](const QVariantMap& snapshot) {
          received[snapshot["path"].toString()] = snapshot["received"].toLongLong();
        });
        QObject::connect(&sample, &QTimer::timeout, &http, observe);
        QObject::connect(&deadline, &QTimer::timeout, &http, [&] {
          observation_only = true;
          cancelled->store(true);
        });
        clock.start();
        sample.start(1000);
        deadline.start(qBound(1000, row["limit_seconds"].toInt(180) * 1000, 900000));
        try {
          resources.fetch(files);
          for (const auto& file : files) {
            QFile input(file.path);
            QCryptographicHash hash(QCryptographicHash::Sha1);
            if (!input.open(QIODevice::ReadOnly) || !hash.addData(&input) ||
                hash.result().toHex() != file.sha1 || input.size() != file.size)
              error = "independent resource verification failed";
          }
        } catch (const std::exception& exception) {
          error = QString::fromUtf8(exception.what());
        }
        sample.stop();
        deadline.stop();
        observe();
        QJsonObject result = row;
        result["size"] = bytes;
        result["elapsed_ms"] = clock.elapsed();
        result["success"] = error.isEmpty();
        result["error"] = error;
        result["samples"] = samples;
        result["observation_only"] = observation_only;
        measurements.append(result);
        if (!save()) {
          ++failures;
          break;
        }
        QFile journal(args[2] + ".http.jsonl");
        if (journal.open(QIODevice::WriteOnly | QIODevice::Truncate))
          journal.write(bugg::diagnostic_snapshot());
        qInfo().noquote() << name << "files" << files.size() << "ms" << clock.elapsed() << error;
        if (!error.isEmpty()) ++failures;
        continue;
      }
      const auto url = QUrl(row["url"].toString());
      const auto expected_size = row["size"].toInteger();
      const auto sha1 = row["sha1"].toString().toLatin1();
      if (!url.isValid() || url.scheme() != "https" || url.hasQuery() || expected_size < 1 ||
          expected_size > qint64(4) * 1024 * 1024 * 1024 || sha1.size() != 40 || name.isEmpty() ||
          name.contains('/') || name.contains('\\')) {
        qCritical("Invalid explicit bounded measurement input");
        ++failures;
        break;
      }
      bugg::HttpClient http(nullptr, {20000, 600000}, row["pool"].toInt(6));
      bugg::HttpRequest request;
      request.url = url;
      request.sha1 = sha1;
      request.expected_size = expected_size;
      request.maximum_bytes = expected_size + 1;
      request.total_ms = qBound(1000, row["limit_seconds"].toInt(180) * 1000, 900000);
      request.output_path = args[3] + '/' + name;
      request.range_connections = qBound(1, row["connections"].toInt(3), 64);
      request.http2_allowed = row["http2"].toBool(true);
      if (QFileInfo::exists(request.output_path)) {
        qCritical("Destination exists; refusing to count a local cache as network traffic");
        ++failures;
        break;
      }
      QEventLoop loop;
      QElapsedTimer clock;
      QTimer sample, deadline;
      deadline.setSingleShot(true);
      qint64 received = 0, first_byte = -1, network_end = -1;
      QJsonArray samples;
      QString error, route;
      int status = 0;
      bool observation_only = false;
      quint64 id = 0;
      const auto observe = [&] {
        samples.append(QJsonObject{{"ms", clock.elapsed()}, {"bytes", received}});
      };
      QObject::connect(&http, &bugg::HttpClient::progress, &loop,
                       [&](quint64 current, qint64 bytes, qint64) {
                         if (current != id) return;
                         if (bytes > 0 && first_byte < 0) first_byte = clock.elapsed();
                         received = qMax(received, bytes);
                         if (received == expected_size && network_end < 0)
                           network_end = clock.elapsed();
                       });
      QObject::connect(&http, &bugg::HttpClient::route_changed, &loop,
                       [&](quint64 current, const QUrl& target) {
                         if (current == id) route = bugg::diagnostic_url(target);
                       });
      QObject::connect(&http, &bugg::HttpClient::response, &loop,
                       [&](quint64 current, const QByteArray&, const QString& failure, int code) {
                         if (current != id) return;
                         error = failure;
                         status = code;
                         loop.quit();
                       });
      QObject::connect(&sample, &QTimer::timeout, &loop, observe);
      QObject::connect(&deadline, &QTimer::timeout, &loop, [&] {
        observation_only = true;
        error = "observation deadline; incomplete download";
        http.cancel(id);
        loop.quit();
      });
      clock.start();
      id = http.request(request);
      sample.start(1000);
      // Deadline is explicitly observation-only, not a successful file download.
      deadline.start(request.total_ms);
      loop.exec();
      sample.stop();
      deadline.stop();
      observe();
      const auto elapsed = clock.elapsed();
      QString actual_sha1;
      if (error.isEmpty()) {
        QFile file(request.output_path);
        QCryptographicHash digest(QCryptographicHash::Sha1);
        if (file.open(QIODevice::ReadOnly) && digest.addData(&file))
          actual_sha1 = QString::fromLatin1(digest.result().toHex());
        if (actual_sha1.toLatin1() != sha1.toLower() || file.size() != expected_size)
          error = "independent final file verification failed";
      }
      QJsonObject result = row;
      result["elapsed_ms"] = elapsed;
      result["received_bytes"] = received;
      result["first_byte_ms"] = first_byte;
      result["network_end_ms"] = network_end;
      result["status"] = status;
      result["route"] = route;
      result["success"] = error.isEmpty();
      result["observation_only"] = observation_only;
      result["error"] = error;
      result["actual_sha1"] = actual_sha1;
      result["samples"] = samples;
      measurements.append(result);
      if (!save()) {
        ++failures;
        break;
      }
      qInfo().noquote() << name << "bytes" << received << "ms" << elapsed << error;
      QFile journal(args[2] + ".http.jsonl");
      if (journal.open(QIODevice::WriteOnly | QIODevice::Truncate))
        journal.write(bugg::diagnostic_snapshot());
      if (!error.isEmpty() && !observation_only) ++failures;
    }
  }));
  app.exec();
  return failures ? 1 : 0;
}
