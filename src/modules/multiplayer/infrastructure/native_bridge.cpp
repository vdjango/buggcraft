#include "modules/multiplayer/infrastructure/native_bridge.h"

#include <QCoreApplication>
#include <QFileInfo>
#include <QJsonDocument>
namespace bugg {
NativeBridge::NativeBridge(QString executable, QObject* parent)
    : QObject(parent), executable_(std::move(executable)) {
  process_.setProcessChannelMode(QProcess::SeparateChannels);
  connect(&process_, &QProcess::readyReadStandardOutput, this, &NativeBridge::receive);
  // 引擎诊断只排空，不让包含运行上下文的 stderr 进入 UI 或增长内存。
  connect(&process_, &QProcess::readyReadStandardError, this,
          [this] { process_.readAllStandardError(); });
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
void NativeBridge::call(const QString& method, const QJsonObject& parameters, Reply complete,
                        Priority priority) {
  const auto id = ++sequence_;
  auto bytes =
      QJsonDocument(
          QJsonObject{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", parameters}})
          .toJson(QJsonDocument::Compact) +
      '\n';
  if (closing_ || queue_.size() >= 32 || bytes.size() > 8192 || !QFileInfo::exists(executable_)) {
    QTimer::singleShot(0, this, [complete] {
      complete({}, QCoreApplication::translate("Bugg", "联机引擎不可用"));
    });
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
    request.complete(object["result"].toObject(), object["error"].toObject()["message"].toString());
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
