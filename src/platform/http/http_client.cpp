#include "platform/http/http_client.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QLockFile>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSaveFile>
#include <QSslCertificate>
#include <QSslConfiguration>
#include <QSslError>
#include <QTemporaryDir>
#include <QTimer>
#include <QUuid>
#include <algorithm>
#include <memory>

#include "platform/diagnostics/diagnostic_log.h"

namespace bugg {
namespace {
QString partial_path(const HttpRequest& options) {
  if (!options.resume || options.method != "GET" || options.output_path.isEmpty() ||
      options.sha1.size() != 40 || options.expected_size < 0 ||
      options.expected_size > options.maximum_bytes || !options.expected_range.isEmpty() ||
      options.headers.contains("Range"))
    return {};
  for (const auto c : options.sha1.toLower())
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return {};
  const QFileInfo target(options.output_path);
  const auto identity = target.fileName().toUtf8() + '\0' + options.sha1.toLower() + '\0' +
                        QByteArray::number(options.expected_size);
  const auto key = QCryptographicHash::hash(identity, QCryptographicHash::Sha256).toHex();
  return target.absolutePath() + "/.bugg-downloads/" + key + ".part";
}
}  // namespace

HttpClient::HttpClient(QObject* parent, HttpTimeouts timeouts)
    : QObject(parent),
      timeouts_{qMax(1, timeouts.idle_ms), qMax(1, timeouts.total_ms)},
      diagnostic_id_(QUuid::createUuid().toString(QUuid::WithoutBraces)) {}

quint64 HttpClient::get(const QUrl& url, const QStringList& blocked_redirect_hosts) {
  HttpRequest options;
  options.url = url;
  options.blocked_redirect_hosts = blocked_redirect_hosts;
  options.total_ms = timeouts_.total_ms;
  return request(options);
}

quint64 HttpClient::request(const HttpRequest& options) {
  const quint64 id = ++sequence_;
  record_diagnostic("http.start",
                    {{"client", diagnostic_id_},
                     {"id", qint64(id)},
                     {"url", diagnostic_url(options.url)},
                     {"method", QString::fromLatin1(options.method)},
                     {"file", QFileInfo(options.output_path).fileName()},
                     {"expected_bytes", options.expected_size},
                     {"total_ms", options.total_ms},
                     {"first_byte_ms", qMax(timeouts_.idle_ms, options.first_byte_ms)},
                     {"idle_ms", timeouts_.idle_ms},
                     {"range", QString::fromLatin1(options.headers.value("Range"))}});
  if (options.parallel_ranges && !QFileInfo::exists(partial_path(options)) &&
      options.method == "GET" && !options.output_path.isEmpty() && !options.sha1.isEmpty() &&
      options.expected_size >= 8 * 1024 * 1024 && options.expected_size <= options.maximum_bytes &&
      !options.headers.contains("Range")) {
    pending_.insert(id, nullptr);
    QTimer::singleShot(0, this, [this, id, options] {
      if (pending_.contains(id)) ranged_request(id, options);
    });
    return id;
  }
  pending_.insert(id, nullptr);
  QTimer::singleShot(0, this, [this, id, options] {
    if (pending_.contains(id)) start_request(id, options);
  });
  return id;
}

void HttpClient::start_request(quint64 id, const HttpRequest& options) {
  auto timing = std::make_shared<QElapsedTimer>();
  timing->start();
  auto first_byte = std::make_shared<qint64>(-1);
  QString invalid;
  if (!options.url.isValid() || !options.url.userInfo().isEmpty() ||
      (options.url.scheme() != "https" && options.url.scheme() != "http"))
    invalid = QCoreApplication::translate("Bugg", "无效的资源地址");
  auto output = std::make_shared<QSaveFile>(options.output_path);
  auto input = std::make_shared<QFile>(options.input_path);
  const auto part_path = partial_path(options);
  auto partial = std::make_shared<QFile>(part_path);
  auto lock = std::make_shared<QLockFile>(part_path + ".lock");
  lock->setStaleLockTime(0);
  auto offset = std::make_shared<qint64>(0);
  auto size = std::make_shared<qint64>(0);
  auto discard = std::make_shared<bool>(false);
  std::shared_ptr<QCryptographicHash> hash;
  if (!options.sha1.isEmpty())
    hash = std::make_shared<QCryptographicHash>(QCryptographicHash::Sha1);
  if (invalid.isEmpty() && options.method == "PUT" && !input->open(QIODevice::ReadOnly))
    invalid = QCoreApplication::translate("Bugg", "无法读取待上传文件");
  if (invalid.isEmpty() && !options.output_path.isEmpty()) {
    if (!QDir().mkpath(QFileInfo(options.output_path).absolutePath()))
      invalid = QCoreApplication::translate("Bugg", "无法写入下载目录");
    else if (part_path.isEmpty()) {
      if (!output->open(QIODevice::WriteOnly))
        invalid = QCoreApplication::translate("Bugg", "无法写入下载目录");
    } else if (QFileInfo(QFileInfo(part_path).absolutePath()).isSymLink() ||
               !QDir().mkpath(QFileInfo(part_path).absolutePath()) || !lock->tryLock(0) ||
               QFileInfo(part_path).isSymLink() || !partial->open(QIODevice::ReadWrite)) {
      invalid = QCoreApplication::translate("Bugg", "下载暂存文件不可写或正在使用");
    } else {
      if (partial->size() >= options.expected_size) partial->resize(0);
      while (!partial->atEnd()) {
        QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents);
        if (!pending_.contains(id)) return;
        const auto bytes = partial->read(1024 * 1024);
        if (bytes.isEmpty() && partial->error() != QFileDevice::NoError) {
          invalid = QCoreApplication::translate("Bugg", "无法读取下载暂存文件");
          break;
        }
        hash->addData(bytes);
      }
      *offset = *size = partial->pos();
    }
  }
  if (!invalid.isEmpty()) {
    pending_.insert(id, nullptr);
    QTimer::singleShot(0, this, [this, id, invalid] {
      if (pending_.remove(id)) {
        emit completed(id, {}, invalid);
        emit response(id, {}, invalid, 0);
      }
    });
    return;
  }
  if (!pending_.contains(id)) return;
  QNetworkRequest request(options.url);
  if (!options.ca_pem.isEmpty()) {
    auto tls = request.sslConfiguration();
    tls.setCaCertificates(QSslCertificate::fromData(options.ca_pem));
    request.setSslConfiguration(tls);
  }
  request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                       QNetworkRequest::UserVerifiedRedirectPolicy);
  request.setMaximumRedirectsAllowed(8);
  request.setRawHeader("User-Agent", "Bugg/" BUGG_VERSION);
  for (auto it = options.headers.begin(); it != options.headers.end(); ++it)
    request.setRawHeader(it.key(), it.value());
  if (!part_path.isEmpty()) {
    request.setRawHeader("Accept-Encoding", "identity");
    if (*offset) request.setRawHeader("Range", "bytes=" + QByteArray::number(*offset) + '-');
  }
  auto* reply = options.method == "PUT"    ? manager_.put(request, input.get())
                : options.method == "POST" ? manager_.post(request, options.body)
                                           : manager_.get(request);
  if (!options.ca_pem.isEmpty()) {
    const auto anchors = QSslCertificate::fromData(options.ca_pem);
    connect(reply, &QNetworkReply::sslErrors, reply,
            [reply, anchors](const QList<QSslError>& errors) {
              // Schannel reports explicitly pinned self-signed leaves as untrusted.
              // Permit only that exact certificate/error pair; hostname, expiry,
              // signature and every other validation error remain fatal.
              if (errors.isEmpty()) return;
              for (const auto& error : errors)
                if (error.error() != QSslError::SelfSignedCertificate ||
                    !anchors.contains(error.certificate()))
                  return;
              reply->ignoreSslErrors(errors);
            });
  }
  reply->setReadBufferSize(1024 * 1024);
  pending_.insert(id, reply);
  if (*offset) {
    emit resumed(id, *offset);
    emit progress(id, *offset, options.expected_size);
  }
  const auto abort_with_error = [reply](const QString& reason) {
    reply->setProperty("failure_reason", reason);
    if (!reply->isFinished()) reply->abort();
  };
  connect(reply, &QNetworkReply::redirected, reply,
          [this, id, reply, options, abort_with_error, timing](const QUrl& target) {
            record_diagnostic("http.redirect", {{"client", diagnostic_id_},
                                                {"id", qint64(id)},
                                                {"from", diagnostic_url(reply->url())},
                                                {"to", diagnostic_url(target)},
                                                {"elapsed_ms", timing->elapsed()}});
            const auto host = target.host().toLower();
            const bool blocked = std::any_of(
                options.blocked_redirect_hosts.begin(), options.blocked_redirect_hosts.end(),
                [&](const auto& item) { return host == item || host.endsWith("." + item); });
            if (blocked || (reply->url().scheme() == "https" && target.scheme() != "https") ||
                !target.userInfo().isEmpty() ||
                ((!options.headers.value("Authorization").isEmpty() ||
                  !options.headers.value("x-api-key").isEmpty() || options.method != "GET") &&
                 (target.host() != options.url.host() || target.port() != options.url.port() ||
                  target.scheme() != options.url.scheme())))
              abort_with_error(
                  QCoreApplication::translate("Bugg", "所选来源重定向到不允许的地址，已阻止请求"));
            else
              reply->redirectAllowed();
          });
  auto* idle = new QTimer(reply);
  idle->setSingleShot(true);
  idle->setInterval(timeouts_.idle_ms);
  connect(reply, &QNetworkReply::socketStartedConnecting, idle,
          [idle, idle_ms = timeouts_.idle_ms] { idle->start(idle_ms); });
  connect(reply, &QNetworkReply::requestSent, idle, [idle, options, idle_ms = timeouts_.idle_ms] {
    idle->start(qMax(idle_ms, options.first_byte_ms));
  });
  connect(idle, &QTimer::timeout, reply, [reply, abort_with_error] {
    reply->setProperty("transport_timeout", true);
    abort_with_error(QCoreApplication::translate("Bugg", "连接或接收数据超时，请重试"));
  });
  auto body = std::make_shared<QByteArray>();
  auto checked_headers = std::make_shared<bool>(false);
  const auto consume = [reply, idle, options, output, partial, offset, part_path, discard,
                        checked_headers, hash, size, body, abort_with_error, timing, first_byte,
                        idle_ms = timeouts_.idle_ms] {
    // abort 会先关闭设备再发 finished；取消/超时路径不再读取已关闭的 reply。
    if (!reply->isOpen()) return;
    const auto bytes = reply->readAll();
    if (!bytes.isEmpty() && *first_byte < 0) *first_byte = timing->elapsed();
    if (!bytes.isEmpty() && !reply->isFinished()) idle->start(idle_ms);
    if (!options.output_path.isEmpty()) {
      const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
      if (status < 200 || status >= 300) return;
      if (!part_path.isEmpty() && !*checked_headers) {
        *checked_headers = true;
        const auto encoding = reply->rawHeader("Content-Encoding").toLower();
        const auto expected = "bytes " + QByteArray::number(*offset) + '-' +
                              QByteArray::number(options.expected_size - 1) + '/' +
                              QByteArray::number(options.expected_size);
        if ((!encoding.isEmpty() && encoding != "identity") ||
            (status == 206 && reply->rawHeader("Content-Range") != expected)) {
          *discard = true;
          abort_with_error(QCoreApplication::translate("Bugg", "服务器返回了错误的续传范围"));
          return;
        }
        if (status == 200 && *offset) {
          // Range was ignored: use this complete response without appending old bytes.
          if (!partial->resize(0) || !partial->seek(0)) {
            abort_with_error(QCoreApplication::translate("Bugg", "无法重置下载暂存文件"));
            return;
          }
          *offset = *size = 0;
          hash->reset();
        }
      }
    }
    *size += bytes.size();
    if (*size > options.maximum_bytes) {
      *discard = true;
      abort_with_error(QCoreApplication::translate("Bugg", "响应超过大小限制"));
      return;
    }
    if (hash) hash->addData(bytes);
    if (options.output_path.isEmpty())
      body->append(bytes);
    else if ((part_path.isEmpty() ? output.get() : static_cast<QFileDevice*>(partial.get()))
                 ->write(bytes) != bytes.size())
      abort_with_error(QCoreApplication::translate("Bugg", "写入下载文件失败"));
  };
  connect(reply, &QNetworkReply::readyRead, this, consume);
  connect(reply, &QNetworkReply::downloadProgress, this,
          [this, id, options, offset, part_path](qint64 received, qint64 total) {
            if (options.method != "PUT")
              emit progress(id, received + *offset,
                            part_path.isEmpty() ? total : options.expected_size);
          });
  connect(reply, &QNetworkReply::uploadProgress, idle,
          [this, id, idle, options](qint64 sent, qint64 total) {
            if (options.method == "PUT") {
              idle->start();
              emit progress(id, sent, total);
            }
          });
  connect(reply, &QNetworkReply::finished, idle, &QTimer::stop);
  idle->start();
  QTimer::singleShot(qMax(1, options.total_ms), reply, [reply, abort_with_error] {
    reply->setProperty("transport_timeout", true);
    abort_with_error(QCoreApplication::translate("Bugg", "请求超过总时限，请重试"));
  });
  connect(reply, &QNetworkReply::finished, this,
          [this, id, reply, consume, options, output, input, partial, lock, part_path, offset,
           discard, hash, size, body, timing, first_byte] {
            consume();
            bool active = pending_.contains(id);
            QString error = reply->property("failure_reason").toString();
            const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            if (error.isEmpty() && !options.expected_range.isEmpty() &&
                (status != 206 || reply->rawHeader("Content-Range") != options.expected_range))
              error = QCoreApplication::translate("Bugg", "服务器不支持所需的分段下载");
            if (error.isEmpty() && reply->error() != QNetworkReply::NoError)
              error = reply->errorString();
            if (error.isEmpty() && status >= 400) error = QString("HTTP %1").arg(status);
            if (error.isEmpty() && options.expected_size >= 0 && *size != options.expected_size) {
              if (*size < options.expected_size) reply->setProperty("incomplete_file", true);
              error = QCoreApplication::translate("Bugg", "文件大小校验失败");
            }
            if (error.isEmpty() && hash && hash->result().toHex() != options.sha1.toLower()) {
              *discard = true;
              error = QCoreApplication::translate("Bugg", "文件 SHA1 校验失败");
            }
            if (!part_path.isEmpty() && active && error.isEmpty()) {
              if (!partial->flush() || !partial->seek(0) || !output->open(QIODevice::WriteOnly))
                error = QCoreApplication::translate("Bugg", "无法提交下载文件");
              while (error.isEmpty() && !partial->atEnd()) {
                QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents);
                if (!pending_.contains(id)) break;
                const auto bytes = partial->read(1024 * 1024);
                if ((bytes.isEmpty() && partial->error() != QFileDevice::NoError) ||
                    output->write(bytes) != bytes.size())
                  error = QCoreApplication::translate("Bugg", "无法提交下载文件");
              }
              active = pending_.contains(id);
            }
            if (!options.output_path.isEmpty()) {
              if (!active || !error.isEmpty())
                output->cancelWriting();
              else if (!output->commit())
                error = QCoreApplication::translate("Bugg", "无法提交下载文件");
            }
            pending_.remove(id);
            partial->close();
            if (!part_path.isEmpty() && (*discard || (active && error.isEmpty())))
              QFile::remove(part_path);
            lock->unlock();
            QJsonObject observed;
            for (const auto& pair : reply->rawHeaderPairs()) {
              const auto name = pair.first.toLower();
              if (name.startsWith("x-bugg-") || name.startsWith("x-mirror-") || name == "x-cache" ||
                  name == "via")
                observed[QString::fromLatin1(name)] =
                    redact_diagnostic(QString::fromLatin1(pair.second.left(256)));
            }
            record_diagnostic("http.finish", {{"client", diagnostic_id_},
                                              {"id", qint64(id)},
                                              {"url", diagnostic_url(reply->url())},
                                              {"status", status},
                                              {"network_error", int(reply->error())},
                                              {"cancelled", !active},
                                              {"success", active && error.isEmpty()},
                                              {"error", redact_diagnostic(error)},
                                              {"received_bytes", *size},
                                              {"resumed_bytes", *offset},
                                              {"expected_bytes", options.expected_size},
                                              {"first_byte_ms", *first_byte},
                                              {"elapsed_ms", timing->elapsed()},
                                              {"route_headers", observed}});
            reply->deleteLater();
            if (active) {
              const auto network_error = reply->error();
              if (reply->property("transport_timeout").toBool() ||
                  reply->property("incomplete_file").toBool() ||
                  network_error == QNetworkReply::ConnectionRefusedError ||
                  network_error == QNetworkReply::RemoteHostClosedError ||
                  network_error == QNetworkReply::HostNotFoundError ||
                  network_error == QNetworkReply::TimeoutError ||
                  network_error == QNetworkReply::SslHandshakeFailedError ||
                  network_error == QNetworkReply::TemporaryNetworkFailureError ||
                  network_error == QNetworkReply::NetworkSessionFailedError) {
                if (reply->property("failure_reason").toString().isEmpty() ||
                    reply->property("transport_timeout").toBool())
                  emit transient_failure(id);
                // A reachable mirror redirecting to a broken upstream must not
                // poison every other cached resource on that mirror.
                if (reply->url().scheme() == options.url.scheme() &&
                    reply->url().host() == options.url.host() &&
                    reply->url().port() == options.url.port())
                  emit unreachable(options.url);
              }
              emit completed(id, error.isEmpty() ? *body : QByteArray{}, error);
              emit response(id, *body, error, status);
            }
          });
}

void HttpClient::cancel(quint64 request_id) {
  for (const auto child : range_children_.take(request_id)) cancel(child);
  if (auto* scope = range_scopes_.take(request_id)) scope->deleteLater();
  const auto reply = pending_.take(request_id);
  if (reply) reply->abort();
}

void HttpClient::ranged_request(quint64 id, const HttpRequest& options) {
  struct Group {
    QTemporaryDir directory;
    QHash<quint64, int> indexes;
    QHash<quint64, qint64> received;
    QStringList parts;
    int done = 0;
    bool fallback = false;
  };
  auto group = std::make_shared<Group>();
  auto* scope = new QObject(this);
  range_scopes_[id] = scope;
  connect(this, &HttpClient::transient_failure, scope, [this, id, group](quint64 child) {
    if (group->fallback && group->indexes.contains(child) && pending_.contains(id))
      emit transient_failure(id);
  });
  const auto finish = [this, id, scope](const QString& error, int status) {
    if (!pending_.remove(id)) return;
    range_children_.remove(id);
    range_scopes_.remove(id);
    scope->deleteLater();
    emit completed(id, {}, error);
    emit response(id, {}, error, status);
  };
  connect(this, &HttpClient::progress, scope,
          [this, id, group, options](quint64 child, qint64 bytes, qint64) {
            if (!group->indexes.contains(child) || !pending_.contains(id)) return;
            group->received[child] = bytes;
            qint64 total = 0;
            for (const auto value : group->received) total += value;
            emit progress(id, total, options.expected_size);
          });
  connect(this, &HttpClient::response, scope,
          [this, id, group, options, finish](quint64 child, const QByteArray&,
                                             const QString& failure, int status) {
            if (!group->indexes.contains(child) || !pending_.contains(id)) return;
            if (group->fallback) {
              finish(failure, status);
              return;
            }
            if (!failure.isEmpty()) {
              for (const auto sibling : range_children_.value(id))
                if (sibling != child) cancel(sibling);
              group->indexes.clear();
              group->received.clear();
              group->fallback = true;
              auto fallback = options;
              fallback.parallel_ranges = false;
              const auto request_id = request(fallback);
              group->indexes[request_id] = 0;
              range_children_[id] = {request_id};
              return;
            }
            if (++group->done != 3) return;
            QSaveFile output(options.output_path);
            QString error;
            if (!QDir().mkpath(QFileInfo(options.output_path).absolutePath()) ||
                !output.open(QIODevice::WriteOnly))
              error = QCoreApplication::translate("Bugg", "无法写入下载目录");
            QCryptographicHash hash(QCryptographicHash::Sha1);
            qint64 written = 0;
            for (const auto& part : group->parts) {
              if (!error.isEmpty()) break;
              QFile input(part);
              if (!input.open(QIODevice::ReadOnly)) {
                error = QCoreApplication::translate("Bugg", "无法读取下载分段");
                break;
              }
              while (!input.atEnd()) {
                QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents);
                if (!pending_.contains(id)) {
                  output.cancelWriting();
                  return;
                }
                const auto bytes = input.read(1024 * 1024);
                if ((bytes.isEmpty() && input.error() != QFileDevice::NoError) ||
                    output.write(bytes) != bytes.size()) {
                  error = QCoreApplication::translate("Bugg", "合并下载文件失败");
                  break;
                }
                written += bytes.size();
                hash.addData(bytes);
              }
            }
            if (error.isEmpty() && (written != options.expected_size ||
                                    hash.result().toHex() != options.sha1.toLower()))
              error = QCoreApplication::translate("Bugg", "文件大小或 SHA1 校验失败");
            if (!error.isEmpty())
              output.cancelWriting();
            else if (!output.commit())
              error = QCoreApplication::translate("Bugg", "无法提交下载文件");
            finish(error, error.isEmpty() ? 200 : status);
          });
  if (!group->directory.isValid()) {
    finish(QCoreApplication::translate("Bugg", "无法创建下载暂存目录"), 0);
    return;
  }
  for (int index = 0; index < 3; ++index) {
    const qint64 first = options.expected_size * index / 3;
    const qint64 last = options.expected_size * (index + 1) / 3 - 1;
    auto part = options;
    part.parallel_ranges = false;
    part.sha1.clear();
    part.expected_size = last - first + 1;
    part.maximum_bytes = part.expected_size + 1;
    part.output_path = group->directory.filePath(QString::number(index));
    part.headers["Range"] = "bytes=" + QByteArray::number(first) + '-' + QByteArray::number(last);
    part.headers["Accept-Encoding"] = "identity";
    part.expected_range = "bytes " + QByteArray::number(first) + '-' + QByteArray::number(last) +
                          '/' + QByteArray::number(options.expected_size);
    group->parts.append(part.output_path);
    const auto child = request(part);
    group->indexes[child] = index;
    range_children_[id].append(child);
  }
}
}  // namespace bugg
