#include "platform/http/http_client.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QHttp1Configuration>
#include <QLockFile>
#include <QMetaObject>
#include <QMutex>
#include <QMutexLocker>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QQueue>
#include <QSaveFile>
#include <QSslCertificate>
#include <QSslConfiguration>
#include <QSslError>
#include <QTemporaryDir>
#include <QTimer>
#include <QUuid>
#include <algorithm>
#include <functional>
#include <memory>

#include "platform/diagnostics/diagnostic_log.h"

namespace bugg {
namespace {
class ProcessRequestBudget {
 public:
  quint64 reserve(QObject* context, std::function<void(quint64)> callback) {
    Waiter ready;
    quint64 ticket = 0;
    bool dispatch = false;
    {
      QMutexLocker lock(&mutex_);
      ticket = ++sequence_;
      Waiter waiter{ticket, context, std::move(callback)};
      states_.insert(ticket, State::Waiting);
      if (active_ < kMaximumRequests && waiting_.isEmpty()) {
        ++active_;
        states_[ticket] = State::Granted;
        ready = std::move(waiter);
        dispatch = true;
      } else {
        waiting_.enqueue(std::move(waiter));
      }
    }
    if (dispatch) dispatch_waiter(std::move(ready));
    return ticket;
  }

  bool activate(quint64 ticket) {
    QMutexLocker lock(&mutex_);
    if (states_.value(ticket) != State::Granted) return false;
    states_[ticket] = State::Active;
    return true;
  }

  void abandon(quint64 ticket) { finish(ticket, false); }
  void release(quint64 ticket) { finish(ticket, true); }

 private:
  enum class State { Waiting, Granted, Active };
  struct Waiter {
    quint64 ticket = 0;
    QPointer<QObject> context;
    std::function<void(quint64)> callback;
  };
  static constexpr int kMaximumRequests = 64;

  void finish(quint64 ticket, bool release_active) {
    Waiter ready;
    bool dispatch = false;
    {
      QMutexLocker lock(&mutex_);
      const auto found = states_.find(ticket);
      if (found == states_.end()) return;
      const auto state = found.value();
      if (state == State::Waiting) {
        for (auto it = waiting_.begin(); it != waiting_.end(); ++it) {
          if (it->ticket == ticket) {
            waiting_.erase(it);
            break;
          }
        }
        states_.erase(found);
        return;
      }
      if (state == State::Active && !release_active) return;
      states_.erase(found);
      --active_;
      while (!waiting_.isEmpty()) {
        auto waiter = waiting_.dequeue();
        if (states_.value(waiter.ticket) != State::Waiting) continue;
        if (!waiter.context) {
          states_.remove(waiter.ticket);
          continue;
        }
        states_[waiter.ticket] = State::Granted;
        ++active_;
        ready = std::move(waiter);
        dispatch = true;
        break;
      }
    }
    if (dispatch) dispatch_waiter(std::move(ready));
  }

  void dispatch_waiter(Waiter waiter) {
    if (!waiter.context) {
      release(waiter.ticket);
      return;
    }
    const auto ticket = waiter.ticket;
    auto* receiver = waiter.context.data();
    if (!QMetaObject::invokeMethod(
            receiver,
            [this, waiter = std::move(waiter)]() mutable {
              if (!waiter.context) {
                release(waiter.ticket);
                return;
              }
              waiter.callback(waiter.ticket);
            },
            Qt::QueuedConnection))
      release(ticket);
  }

  QMutex mutex_;
  QQueue<Waiter> waiting_;
  QHash<quint64, State> states_;
  quint64 sequence_ = 0;
  int active_ = 0;
};

ProcessRequestBudget& process_request_budget() {
  static ProcessRequestBudget budget;
  return budget;
}

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

HttpClient::HttpClient(QObject* parent, HttpTimeouts timeouts, int connections_per_host)
    : QObject(parent),
      timeouts_{qMax(1, timeouts.idle_ms), qMax(1, timeouts.total_ms),
                qMax(1, timeouts.slow_window_ms)},
      connections_per_host_(qBound(1, connections_per_host, 64)),
      diagnostic_id_(QUuid::createUuid().toString(QUuid::WithoutBraces)) {}

HttpClient::~HttpClient() {
  const auto tickets = request_slots_.values();
  request_slots_.clear();
  for (const auto ticket : tickets) process_request_budget().release(ticket);
}

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
  const QFileInfo partial(partial_path(options));
  if (options.parallel_ranges && options.range_connections > 1 &&
      range_disabled_until_.value(options.url) <= QDateTime::currentMSecsSinceEpoch() &&
      (!partial.exists() || partial.size() == 0) && options.method == "GET" &&
      !options.output_path.isEmpty() && !options.sha1.isEmpty() &&
      options.expected_size >= 8 * 1024 * 1024 && options.expected_size <= options.maximum_bytes &&
      !options.headers.contains("Range")) {
    pending_.insert(id, nullptr);
    QTimer::singleShot(0, this, [this, id, options] {
      if (pending_.contains(id)) ranged_request(id, options);
    });
    return id;
  }
  pending_.insert(id, nullptr);
  queued_.insert(id, options);
  QTimer::singleShot(0, this, &HttpClient::pump_requests);
  return id;
}

void HttpClient::pump_requests() {
  while (request_slots_.size() < connections_per_host_ && !queued_.isEmpty()) {
    auto first = queued_.begin();
    while (first != queued_.end() && request_slots_.contains(first.key())) ++first;
    if (first == queued_.end()) break;
    const auto id = first.key();
    if (!pending_.contains(id)) {
      queued_.erase(first);
      continue;
    }
    const QPointer<HttpClient> guard(this);
    const auto ticket = process_request_budget().reserve(this, [guard, id](quint64 granted) {
      if (guard) guard->start_granted_request(id, granted);
    });
    request_slots_.insert(id, ticket);
  }
}

void HttpClient::start_granted_request(quint64 id, quint64 ticket) {
  if (request_slots_.value(id) != ticket) {
    process_request_budget().abandon(ticket);
    return;
  }
  if (!pending_.contains(id)) {
    release_request_slot(id);
    return;
  }
  const auto options = queued_.take(id);
  if (!process_request_budget().activate(ticket)) {
    release_request_slot(id);
    QTimer::singleShot(0, this, &HttpClient::pump_requests);
    return;
  }
  start_request(id, options);
}

void HttpClient::release_request_slot(quint64 id) {
  const auto ticket = request_slots_.take(id);
  if (ticket) process_request_budget().release(ticket);
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
  // Internal pieces live in the range group's private temporary directory.
  // Only the final verified artifact needs an atomic, durable commit.
  auto piece =
      std::make_shared<QFile>(options.expected_range.isEmpty() ? QString{} : options.output_path);
  const bool is_piece = !options.expected_range.isEmpty();
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
    else if (is_piece) {
      if (!piece->open(QIODevice::WriteOnly))
        invalid = QCoreApplication::translate("Bugg", "无法写入下载目录");
    } else if (part_path.isEmpty()) {
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
        release_request_slot(id);
        emit completed(id, {}, invalid);
        emit response(id, {}, invalid, 0);
        pump_requests();
      }
    });
    return;
  }
  if (!pending_.contains(id)) return;
  QNetworkRequest request(options.url);
  auto http1 = request.http1Configuration();
  http1.setNumberOfConnectionsPerHost(connections_per_host_);
  request.setHttp1Configuration(http1);
  request.setAttribute(QNetworkRequest::Http2AllowedAttribute, options.http2_allowed);
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
  emit route_changed(id, options.url);
  if (*offset) {
    emit resumed(id, *offset);
    emit progress(id, *offset, options.expected_size);
  }
  const auto abort_with_error = [reply](const QString& reason) {
    reply->setProperty("failure_reason", reason);
    if (!reply->isFinished()) reply->abort();
  };
  auto redirect_from = std::make_shared<QUrl>(options.url);
  connect(reply, &QNetworkReply::redirected, reply,
          [this, id, reply, options, abort_with_error, timing, redirect_from](const QUrl& target) {
            record_diagnostic("http.redirect", {{"client", diagnostic_id_},
                                                {"id", qint64(id)},
                                                {"from", diagnostic_url(*redirect_from)},
                                                {"to", diagnostic_url(target)},
                                                {"elapsed_ms", timing->elapsed()}});
            const auto previous = *redirect_from;
            *redirect_from = target;
            const auto host = target.host().toLower();
            const bool blocked = std::any_of(
                options.blocked_redirect_hosts.begin(), options.blocked_redirect_hosts.end(),
                [&](const auto& item) { return host == item || host.endsWith("." + item); });
            if (blocked || (previous.scheme() == "https" && target.scheme() != "https") ||
                !target.userInfo().isEmpty() ||
                ((!options.headers.value("Authorization").isEmpty() ||
                  !options.headers.value("x-api-key").isEmpty() || options.method != "GET") &&
                 (target.host() != options.url.host() || target.port() != options.url.port() ||
                  target.scheme() != options.url.scheme())))
              abort_with_error(
                  QCoreApplication::translate("Bugg", "所选来源重定向到不允许的地址，已阻止请求"));
            else {
              emit route_changed(id, target);
              reply->redirectAllowed();
            }
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
  auto checked_range = std::make_shared<bool>(false);
  auto speed_started = std::make_shared<qint64>(-1);
  auto speed_bytes = std::make_shared<qint64>(0);
  const auto consume = [this, id, reply, idle, options, output, piece, is_piece, partial, offset,
                        part_path, discard, checked_range, checked_headers, hash, size, body,
                        abort_with_error, timing, first_byte, idle_ms = timeouts_.idle_ms,
                        speed_started, speed_bytes, slow_window_ms = timeouts_.slow_window_ms] {
    // abort 会先关闭设备再发 finished；取消/超时路径不再读取已关闭的 reply。
    if (!reply->isOpen()) return;
    const auto bytes = reply->readAll();
    if (!bytes.isEmpty() && *first_byte < 0) *first_byte = timing->elapsed();
    if (!bytes.isEmpty() && !reply->isFinished()) idle->start(idle_ms);
    if (!options.output_path.isEmpty()) {
      const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
      if (status < 200 || status >= 300) return;
      if (!options.expected_range.isEmpty() && !*checked_range) {
        *checked_range = true;
        const auto encoding = reply->rawHeader("Content-Encoding").toLower();
        if (status != 206 || reply->rawHeader("Content-Range") != options.expected_range ||
            (!encoding.isEmpty() && encoding != "identity")) {
          abort_with_error(QCoreApplication::translate("Bugg", "服务器不支持所需的分段下载"));
          return;
        }
        emit range_accepted(id);
      }
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
    else if ((is_piece              ? static_cast<QFileDevice*>(piece.get())
              : part_path.isEmpty() ? output.get()
                                    : static_cast<QFileDevice*>(partial.get()))
                 ->write(bytes) != bytes.size())
      abort_with_error(QCoreApplication::translate("Bugg", "写入下载文件失败"));
    if (options.minimum_bytes_per_second > 0 && !options.output_path.isEmpty() &&
        !bytes.isEmpty() && !reply->isFinished() &&
        (options.expected_size < 0 || *size < options.expected_size)) {
      const auto now = timing->elapsed();
      if (*speed_started < 0) *speed_started = now;
      *speed_bytes += bytes.size();
      const auto elapsed = now - *speed_started;
      if (elapsed >= slow_window_ms) {
        if (*speed_bytes * 1000 / qMax<qint64>(1, elapsed) < options.minimum_bytes_per_second) {
          reply->setProperty("slow_transfer", true);
          abort_with_error(QCoreApplication::translate("Bugg", "当前来源传输过慢，正在切换来源"));
        }
        *speed_started = now;
        *speed_bytes = 0;
      }
    }
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
          [this, id, reply, consume, options, output, piece, is_piece, input, partial, lock,
           part_path, offset, discard, hash, size, body, timing, first_byte] {
            consume();
            bool active = pending_.contains(id);
            QString error = reply->property("failure_reason").toString();
            const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            if (error.isEmpty() && status >= 200 && status < 300 &&
                !options.expected_range.isEmpty() &&
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
            if (is_piece) {
              if (active && error.isEmpty() && !piece->flush())
                error = QCoreApplication::translate("Bugg", "无法提交下载文件");
              piece->close();
              if (!active || !error.isEmpty()) piece->remove();
            } else if (!options.output_path.isEmpty()) {
              if (!active || !error.isEmpty())
                output->cancelWriting();
              else if (!output->commit())
                error = QCoreApplication::translate("Bugg", "无法提交下载文件");
            }
            pending_.remove(id);
            release_request_slot(id);
            QTimer::singleShot(0, this, &HttpClient::pump_requests);
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
            record_diagnostic(
                "http.finish",
                {{"client", diagnostic_id_},
                 {"id", qint64(id)},
                 {"url", diagnostic_url(reply->url())},
                 {"status", status},
                 {"http2", reply->attribute(QNetworkRequest::Http2WasUsedAttribute).toBool()},
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
              if (reply->property("slow_transfer").toBool()) emit transient_failure(id);
              const bool same_origin = reply->url().scheme() == options.url.scheme() &&
                                       reply->url().host() == options.url.host() &&
                                       reply->url().port() == options.url.port();
              if (same_origin && (status == 502 || status == 503 || status == 504))
                emit unreachable(options.url);
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
                if (same_origin) emit unreachable(options.url);
              }
              emit completed(id, error.isEmpty() ? *body : QByteArray{}, error);
              emit response(id, *body, error, status);
            }
          });
}

void HttpClient::cancel(quint64 request_id) {
  queued_.remove(request_id);
  for (const auto child : range_children_.take(request_id)) cancel(child);
  if (auto* scope = range_scopes_.take(request_id)) scope->deleteLater();
  const auto reply = pending_.take(request_id);
  if (reply) {
    reply->abort();
  } else {
    release_request_slot(request_id);
  }
  QTimer::singleShot(0, this, &HttpClient::pump_requests);
}

void HttpClient::ranged_request(quint64 id, const HttpRequest& options) {
  struct Group {
    QTemporaryDir directory;
    QHash<quint64, int> indexes;
    QHash<quint64, qint64> received;
    QHash<int, int> attempts;
    QHash<quint64, qint64> started;
    QHash<quint64, qint64> advanced;
    QElapsedTimer clock;
    QStringList parts;
    qint64 completed_bytes = 0;
    int done = 0;
    int next = 0;
    int retry_wait = 0;
    bool fallback = false;
    bool expanded = false;
  };
  auto group = std::make_shared<Group>();
  group->clock.start();
  const auto connections =
      qBound(2, options.range_connections, qMin(64, int(options.expected_size / (512 * 1024))));
  const int part_count = options.expected_size >= 64 * 1024 * 1024
                             ? int((options.expected_size + 512 * 1024 - 1) / (512 * 1024))
                             : connections;
  auto* scope = new QObject(this);
  range_scopes_[id] = scope;
  const auto start_part = [this, id, group, options, part_count](int index) {
    const qint64 first = options.expected_size * index / part_count;
    const qint64 last = options.expected_size * (index + 1) / part_count - 1;
    ++group->attempts[index];
    auto part = options;
    part.parallel_ranges = false;
    part.minimum_bytes_per_second = 0;
    part.sha1.clear();
    part.expected_size = last - first + 1;
    part.maximum_bytes = part.expected_size + 1;
    part.output_path = group->directory.filePath(QString::number(index));
    part.headers["Range"] = "bytes=" + QByteArray::number(first) + '-' + QByteArray::number(last);
    part.headers["Accept-Encoding"] = "identity";
    part.expected_range = "bytes " + QByteArray::number(first) + '-' + QByteArray::number(last) +
                          '/' + QByteArray::number(options.expected_size);
    const auto child = request(part);
    group->indexes[child] = index;
    range_children_[id].append(child);
  };
  const auto fill = [this, id, group, start_part, connections, part_count] {
    const int limit = group->expanded ? connections : 1;
    while (pending_.contains(id) && !group->fallback &&
           group->indexes.size() + group->retry_wait < limit && group->next < part_count)
      start_part(group->next++);
  };
  connect(this, &HttpClient::range_accepted, scope, [this, id, group, fill](quint64 child) {
    if (!pending_.contains(id) || group->fallback || group->expanded ||
        !group->indexes.contains(child))
      return;
    group->expanded = true;
    fill();
  });

  connect(this, &HttpClient::route_changed, scope,
          [this, id, group](quint64 child, const QUrl& url) {
            if (group->indexes.contains(child) && pending_.contains(id)) {
              if (!group->started.contains(child)) group->started[child] = group->clock.elapsed();
              emit route_changed(id, url);
            }
          });
  // Reuse idle capacity at the tail instead of waiting tens of seconds for one
  // degraded connection. Each small piece has the same three-attempt budget.
  if (part_count > connections) {
    auto* tail = new QTimer(scope);
    connect(tail, &QTimer::timeout, scope, [this, id, group, part_count, connections, start_part] {
      if (!pending_.contains(id) || group->fallback || group->next != part_count ||
          group->indexes.size() + group->retry_wait >= connections / 2)
        return;
      const auto children = group->indexes.keys();
      for (const auto child : children) {
        const int index = group->indexes.value(child);
        const auto age = group->clock.elapsed() - group->started.value(child);
        const auto quiet =
            group->clock.elapsed() - group->advanced.value(child, group->started.value(child));
        if (!group->started.contains(child) || group->attempts[index] >= 3 || age < 3000 ||
            (quiet < 2000 && (age < 8000 || group->received.value(child) * 1000 / age >= 65536)))
          continue;
        group->indexes.remove(child);
        group->started.remove(child);
        group->advanced.remove(child);
        group->received.remove(child);
        range_children_[id].removeOne(child);
        cancel(child);
        record_diagnostic(
            "http.range_tail_retry",
            {{"parent", qint64(id)}, {"part", index}, {"attempt", group->attempts[index]}});
        start_part(index);
      }
    });
    tail->start(1000);
  }
  const auto finish = [this, id, scope](const QString& error, int status) {
    if (!pending_.remove(id)) return;
    for (const auto child : range_children_.take(id)) cancel(child);
    range_scopes_.remove(id);
    scope->deleteLater();
    emit completed(id, {}, error);
    emit response(id, {}, error, status);
  };
  connect(this, &HttpClient::progress, scope,
          [this, id, group, options](quint64 child, qint64 bytes, qint64) {
            if (!group->indexes.contains(child) || !pending_.contains(id)) return;
            if (bytes > group->received.value(child))
              group->advanced[child] = group->clock.elapsed();
            group->received[child] = bytes;
            qint64 total = group->completed_bytes;
            for (const auto value : group->received) total += value;
            emit progress(id, total, options.expected_size);
          });
  connect(this, &HttpClient::response, scope,
          [this, id, group, options, finish, fill, start_part, part_count, scope](
              quint64 child, const QByteArray&, const QString& failure, int status) {
            if (!group->indexes.contains(child) || !pending_.contains(id)) return;
            if (group->fallback) {
              finish(failure, status);
              return;
            }
            const int index = group->indexes.take(child);
            group->received.remove(child);
            group->started.remove(child);
            group->advanced.remove(child);
            range_children_[id].removeOne(child);
            if (!failure.isEmpty()) {
              // Preserve successful pieces. Do not retry HTTP rate limits here.
              if ((status == 0 || status == 206) && group->attempts[index] < 3) {
                group->received.remove(child);
                ++group->retry_wait;
                record_diagnostic("http.range_retry", {{"parent", qint64(id)},
                                                       {"part", index},
                                                       {"attempt", group->attempts[index]},
                                                       {"status", status}});
                QTimer::singleShot(250 * group->attempts[index], scope,
                                   [this, id, group, start_part, index] {
                                     --group->retry_wait;
                                     if (pending_.contains(id) && !group->fallback)
                                       start_part(index);
                                   });
                return;
              }
              if (status == 200 || status == 416) {
                if (range_disabled_until_.size() >= 256) range_disabled_until_.clear();
                range_disabled_until_[options.url] = QDateTime::currentMSecsSinceEpoch() + 300000;
              }
              for (const auto sibling : range_children_.value(id))
                if (sibling != child) cancel(sibling);
              // Real failures should reach the resource owner's next route.
              // Only an origin that refuses Range needs a same-route full GET.
              if (status != 200 && status != 416) {
                if (status == 0 || status == 206) emit transient_failure(id);
                finish(failure, status);
                return;
              }
              group->indexes.clear();
              group->received.clear();
              group->completed_bytes = 0;
              group->fallback = true;
              auto fallback = options;
              fallback.parallel_ranges = false;
              const auto request_id = request(fallback);
              group->indexes[request_id] = 0;
              range_children_[id] = {request_id};
              return;
            }
            group->completed_bytes += options.expected_size * (index + 1) / part_count -
                                      options.expected_size * index / part_count;
            if (++group->done != part_count) {
              fill();
              return;
            }
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
  for (int index = 0; index < part_count; ++index)
    group->parts.append(group->directory.filePath(QString::number(index)));
  fill();
}
}  // namespace bugg
