#ifndef BUGG_MODULES_MULTIPLAYER_INFRASTRUCTURE_NATIVE_BRIDGE_H_
#define BUGG_MODULES_MULTIPLAYER_INFRASTRUCTURE_NATIVE_BRIDGE_H_
#include <QJsonObject>
#include <QProcess>
#include <QQueue>
#include <QTimer>
#include <functional>
namespace bugg {
/// C++ 联机引擎的唯一 JSON-RPC 进程通道。GUI 异步、串行有界；不解释房间业务。
class NativeBridge : public QObject {
  Q_OBJECT
 public:
  using Reply = std::function<void(const QJsonObject&, const QString&)>;
  enum class Priority { Interactive, Background };
  /// 统一以 --native-bridge 运行原生子进程，可传独立桥或单文件启动器路径。
  explicit NativeBridge(QString executable, QObject* parent = nullptr);
  /// GUI 入队，最长 60 秒；回调在 GUI，退出/进程故障令所有未完成请求失败。
  /// 仅尚未发送的后台请求让位；同级 FIFO，已经发送的请求不抢占。
  void call(const QString& method, const QJsonObject& parameters, Reply complete,
            Priority priority = Priority::Interactive);
  void shutdown();
  bool busy() const { return process_.state() != QProcess::NotRunning; }
 signals:
  void drained();
  void disconnected(const QString& error);

 private:
  struct Request {
    qint64 id;
    QByteArray bytes;
    Reply complete;
    Priority priority;
  };
  void dispatch();
  void receive();
  void fail(const QString& error);
  QProcess process_;
  QTimer timeout_, terminate_;
  QQueue<Request> queue_;
  QByteArray input_;
  QString executable_;
  qint64 sequence_ = 0;
  bool pending_ = false, closing_ = false;
};
}  // namespace bugg
#endif
