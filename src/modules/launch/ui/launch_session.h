#ifndef BUGG_MODULES_LAUNCH_UI_LAUNCH_SESSION_H_
#define BUGG_MODULES_LAUNCH_UI_LAUNCH_SESSION_H_

#include <QtQml/qqmlregistration.h>

#include <QObject>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

#include "bugg_presentation_export.h"
#include "contracts/game_runtime.h"

namespace bugg {

/// launch 模块的窗口级启动呈现；无后端时明确失败，不创建真实游戏进程。
/// 仅 preview_enabled=true 的测试可用 QTimer 推进演示。
/// identity_status 消费同一身份快照，页面不另写身份检查或启动状态机。
class BUGG_PRESENTATION_EXPORT LaunchSession : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QVariantMap status READ status NOTIFY status_changed)
  Q_PROPERTY(QVariantList instances MEMBER instances_)
  Q_PROPERTY(QVariantMap identity_status MEMBER identity_status_ NOTIFY status_changed)
  Q_PROPERTY(bool can_start READ can_start NOTIFY status_changed)
  Q_PROPERTY(bool automatic MEMBER automatic_)
  Q_PROPERTY(bool preview_enabled MEMBER preview_enabled_)
  Q_PROPERTY(QObject* service READ service WRITE set_service NOTIFY status_changed)

 public:
  explicit LaunchSession(QObject* parent = nullptr);
  QVariantMap status() const { return status_; }
  QObject* service() const { return service_; }
  void set_service(QObject* service);
  bool can_start() const { return preflight().isEmpty(); }
  /// 身份确认的唯一检查：空串表示通过，否则返回可读原因；can_start/start 共用。
  Q_INVOKABLE QString preflight() const;
  /// index 为现有实例索引；无身份发 identity_required，活动中的重复请求忽略。
  Q_INVOKABLE void start(int index, const QVariantMap& contributions = {});
  /// 只推进 preparing/stopping，取消后的迟到事件不能重启。
  Q_INVOKABLE void advance();
  /// 取消准备或清除失败，立即恢复 idle；不等待阻塞操作。
  Q_INVOKABLE void cancel();
  /// 仅运行态进入 stopping；finish/演示完成后恢复 idle。
  Q_INVOKABLE void stop();
  Q_INVOKABLE void finish();
  /// reason 保留在失败快照，允许重试；不修改选中身份。
  Q_INVOKABLE void fail(const QString& reason);

 signals:
  void status_changed();
  void identity_required();

 private:
  void show(const QString& state, const QString& title = {}, const QString& detail = {},
            double progress = -1, const QString& stage = {});
  void show_step();
  QVariantMap status_{{"state", "idle"}, {"preview", false}};
  QVariantMap identity_status_;
  QVariantList instances_;
  QTimer timer_;
  int index_ = -1;
  int step_ = 0;
  bool automatic_ = true;
  bool preview_enabled_ = false;
  GameRuntimePort* service_ = nullptr;
};

}  // namespace bugg

#endif  // BUGG_MODULES_LAUNCH_UI_LAUNCH_SESSION_H_
