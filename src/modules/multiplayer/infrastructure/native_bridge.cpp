#include "modules/multiplayer/infrastructure/native_bridge.h"

#include <QCoreApplication>
#include <QFileInfo>
#include <QJsonDocument>
#include <QProcessEnvironment>

#include "platform/diagnostics/diagnostic_log.h"
namespace bugg {
NativeBridge::NativeBridge(QString executable, QObject* parent, const QString& diagnostic_root)
    : QObject(parent), executable_(std::move(executable)) {
  if (!diagnostic_root.isEmpty()) relocate_diagnostics(diagnostic_root);
  process_.setProcessChannelMode(QProcess::SeparateChannels);
  connect(&process_, &QProcess::readyReadStandardOutput, this, &NativeBridge::receive);
  // Drain and redact bounded diagnostics; never retain raw unbounded stderr.
  connect(&process_, &QProcess::readyReadStandardError, this, [this] {
    const auto bytes = process_.readAllStandardError();
    record_diagnostic("bridge.output", {{"message", QString::fromUtf8(bytes.first(12000))}});
  });
  connect(&process_, &QProcess::started, this, &NativeBridge::dispatch);
  connect(&process_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
    if (error == QProcess::FailedToStart)
      fail(QCoreApplication::translate("Bugg", "联机引擎无法启动"));
  });
  connect(&process_, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this, [this] {
    timeout_.stop();
    terminate_.stop();
    const auto error = QCoreApplication::translate("Bugg", "联机连接已结束");
    fail(error);
    if (!closing_) emit disconnected(error);
    emit drained();
  });
  timeout_.setSingleShot(true);
  timeout_.setInterval(60000);
  connect(&timeout_, &QTimer::timeout, this, [this] {
    fail(QCoreApplication::translate("Bugg", "联机节点响应超时"));
    process_.kill();
  });
  terminate_.setSingleShot(true);
  terminate_.setInterval(3000);
  connect(&terminate_, &QTimer::timeout, &process_, &QProcess::kill);
}
NativeBridge::~NativeBridge() {
  // QProcess may emit finished from its destructor, after queue_ is destroyed.
  // Normal shutdown still drains asynchronously before this owner is released.
  process_.disconnect(this);
}
void NativeBridge::relocate_diagnostics(const QString& directory) {
  auto environment = QProcessEnvironment::systemEnvironment();
  environment.insert("BUGGCRAFT_BRIDGE_LOG_DIR", directory);
  process_.setProcessEnvironment(environment);
}
void NativeBridge::call(const QString& method, const QJsonObject& parameters, Reply complete,
                        Priority priority) {
  if (priority == Priority::Interactive) record_diagnostic("bridge.request", {{"method", method}});
  const auto id = ++sequence_;
  auto bytes =
      QJsonDocument(
          QJsonObject{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", parameters}})
          .toJson(QJsonDocument::Compact) +
      '\n';
  QString reason, error;
  if (closing_) {
    reason = "closing";
    error = QCoreApplication::translate("Bugg", "联机服务正在关闭");
  } else if (queue_.size() >= 32) {
    reason = "queue_full";
    error = QCoreApplication::translate("Bugg", "联机请求较多，请稍后重试");
  } else if (bytes.size() > 8192) {
    reason = "request_too_large";
    error = QCoreApplication::translate("Bugg", "联机请求内容超过限制，请提交日志反馈");
  } else if (!QFileInfo::exists(executable_)) {
    reason = "executable_missing";
    error = QCoreApplication::translate("Bugg", "联机引擎文件缺失，请重新下载启动器");
  }
  if (!reason.isEmpty()) {
    record_diagnostic("bridge.rejected", {{"method", method},
                                          {"reason", reason},
                                          {"bytes", bytes.size()},
                                          {"queued", queue_.size()}});
    QTimer::singleShot(0, this, [complete, error] { complete({}, error); });
    return;
  }
  auto position = queue_.size();
  if (priority == Priority::Interactive) {
    for (auto index = pending_ ? 1 : 0; index < queue_.size(); ++index)
      if (queue_[index].priority == Priority::Background) {
        position = index;
        break;
      }
  }
  queue_.insert(position, {id, bytes, std::move(complete), priority});
  if (process_.state() == QProcess::NotRunning) {
    process_.setWorkingDirectory(QFileInfo(executable_).absolutePath());
    process_.start(executable_, {"--native-bridge"});
  } else
    dispatch();
}
void NativeBridge::dispatch() {
  if (pending_ || closing_ || queue_.isEmpty() || process_.state() != QProcess::Running) return;
  pending_ = true;
  if (process_.write(queue_.head().bytes) < 0) {
    fail(QCoreApplication::translate("Bugg", "联机引擎写入失败"));
    return;
  }
  timeout_.start();
}
void NativeBridge::receive() {
  input_ += process_.readAllStandardOutput();
  if (input_.size() > 4 * 1024 * 1024) {
    fail(QCoreApplication::translate("Bugg", "联机响应超过限制"));
    process_.kill();
    return;
  }
  while (input_.contains('\n')) {
    const auto at = input_.indexOf('\n');
    const auto object = QJsonDocument::fromJson(input_.left(at)).object();
    input_.remove(0, at + 1);
    if (!pending_ || queue_.isEmpty() || object["id"].toInteger() != queue_.head().id) continue;
    auto request = queue_.dequeue();
    pending_ = false;
    timeout_.stop();
    const auto error = object["error"].toObject()["message"].toString();
    if (!error.isEmpty())
      record_diagnostic("bridge.failed", {{"id", request.id}, {"error", error}});
    request.complete(object["result"].toObject(), error);
    dispatch();
  }
}
void NativeBridge::fail(const QString& error) {
  pending_ = false;
  input_.clear();
  auto pending = std::exchange(queue_, {});
  for (const auto& request : pending) request.complete({}, error);
}
void NativeBridge::shutdown() {
  if (closing_) return;
  closing_ = true;
  timeout_.stop();
  fail(QCoreApplication::translate("Bugg", "已取消"));
  if (busy()) {
    process_.closeWriteChannel();
    terminate_.start();
  } else
    emit drained();
}
}  // namespace bugg
