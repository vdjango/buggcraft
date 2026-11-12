#ifndef BUGG_CONTRACTS_GAME_RUNTIME_H_
#define BUGG_CONTRACTS_GAME_RUNTIME_H_
#include <QObject>
#include <QVariantMap>

#include "bugg_contracts_export.h"

namespace bugg {
/// 仅 C++ 传递，不注册 QML，不输出到日志。
struct GameIdentity {
  QString name;
  QString uuid;
  QString access_token;
  QString kind;
  QString xuid;
  QString client_id;
};

/// 真实认证服务端口；GUI 线程异步通知，取消后旧请求不产生身份。
class BUGG_CONTRACTS_EXPORT AccountPort : public QObject {
  Q_OBJECT
 public:
  using QObject::QObject;
  /// 无输入；异步 authentication 报设备码/失败，profile_ready 只在完整授权后发出。
  virtual void begin() = 0;
  /// GUI 幂等撤销请求和轮询；等待凭据的 operation 得到取消错误。
  virtual void cancel() = 0;
  /// 清本机会话并异步删除受保护凭据；不代表云端全部会话撤销。
  virtual void logout() = 0;
  /// operation 为调用者代数，profile_id 为保留角色 ID；credentials_ready 原样关联结果。
  /// 按需刷新；令牌只通过 C++ 值回传，失败 identity 为空。
  virtual void acquire(quint64 operation, const QString& profile_id) = 0;
 signals:
  void authentication(const QString& state, const QString& code, const QString& error);
  void profile_ready(const QString& name);
  void credentials_ready(quint64 operation, const bugg::GameIdentity& identity,
                         const QString& error);
};

/// 安装/房间同步/首页/房间启动共同端口。稳定实例 ID，不能依赖页面数组下标。
class BUGG_CONTRACTS_EXPORT GameRuntimePort : public QObject {
  Q_OBJECT
 public:
  using QObject::QObject;
  /// 安装规格 name/game/loader/loaderVersion；异步状态由任务快照通知，取消保留有效缓存。
  virtual void install(const QVariantMap& specification) = 0;
  /// GUI 线程，task_id 指向自有任务；发取消意图，完成快照确认后才释放文件锁。
  virtual void cancel_task(const QString& task_id) = 0;
  /// GUI 异步；稳定实例/角色 ID 和 jvm/game/classpath 贡献 → launch_changed。
  /// 准备失败保留错误，取消不再推进；真实进程创建成功才进入 running。
  virtual void launch(const QString& instance_id, const QString& profile_id,
                      const QVariantMap& contributions = {}) = 0;
  /// 仅取消准备，不终止已运行游戏；迟到凭据失效。
  virtual void cancel_launch() = 0;
  /// 仅停止自有游戏 PID；异步等待真实退出，不在 GUI waitForFinished。
  virtual void stop_game() = 0;
 signals:
  void launch_changed(const QVariantMap& status);
};
}  // namespace bugg
Q_DECLARE_METATYPE(bugg::GameIdentity)
#endif
