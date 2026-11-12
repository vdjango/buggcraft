#ifndef BUGG_MODULES_ACCOUNT_UI_IDENTITY_SESSION_H_
#define BUGG_MODULES_ACCOUNT_UI_IDENTITY_SESSION_H_

#include <QtQml/qqmlregistration.h>

#include <QObject>
#include <QTimer>
#include <QVariantMap>

#include "bugg_presentation_export.h"
#include "contracts/game_runtime.h"

namespace bugg {

/// account 模块的窗口级身份呈现；GUI 线程，授权/凭据委托 AccountPort。
/// 页面共用非敏感 status，分别保留成功的微软/离线角色；不持有真实凭据。
class BUGG_PRESENTATION_EXPORT IdentitySession : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QVariantMap status READ status NOTIFY status_changed)
  Q_PROPERTY(QVariantMap saved_state READ saved_state NOTIFY status_changed)
  Q_PROPERTY(bool automatic MEMBER automatic_)
  Q_PROPERTY(bool preview_enabled MEMBER preview_enabled_ NOTIFY status_changed)
  Q_PROPERTY(QObject* service READ service WRITE set_service NOTIFY status_changed)

 public:
  explicit IdentitySession(QObject* parent = nullptr);
  QVariantMap status() const { return status_; }
  /// 非敏感离线角色与上次选择；微软角色须经 AccountPort 恢复后才可用。
  QVariantMap saved_state() const;
  Q_INVOKABLE void restore_state(const QVariantMap& state);
  QObject* service() const { return service_; }
  /// GUI 线程注入应用认证端口；不持有服务寿命，页面不能访问凭据。
  void set_service(QObject* service);
  /// 提交 3–16 位 ASCII 字母/数字/下划线名称；失败返回 false 并保留原身份。
  Q_INVOKABLE bool use_offline(const QString& name);
  /// GUI 线程：选择本会话保留的角色 id，复用 select；未知 id 返回 false，不改变身份。
  /// 无 I/O；启动期间的身份锁由命令装配层执行，成功发 committed。
  Q_INVOKABLE bool activate_profile(const QString& id);
  /// 已有微软身份直接复用 select；无服务时返回不可用，不提交身份。
  /// 仅 preview_enabled=true 的测试可启动设备码模拟；automatic=false 手动驱动。
  Q_INVOKABLE void begin_microsoft();
  Q_INVOKABLE void complete_microsoft();
  /// 只接受 authorizing 状态的完成事件，取消后的迟到结果无效。
  Q_INVOKABLE void finish_microsoft();
  /// 委托端口取消授权，停止测试驱动并保留当前身份，可重复调用。
  Q_INVOKABLE void cancel_microsoft();
  /// GUI 线程幂等登出；取消授权、清空微软记录，选中的微软身份回退离线或未选择。
  /// 复用 select 更新身份，凭据删除由端口异步执行；调用方沿用启动活动期间的身份锁。
  Q_INVOKABLE void logout_microsoft();

 signals:
  void status_changed();
  void committed();

 private:
  void select(const QString& name, const QString& kind, const QString& caption, bool activate = true);
  void set_auth(const QString& state, const QString& code = {}, const QString& error = {});
  QVariantMap status_{{"name", ""},
                      {"kind", ""},
                      {"initials", "?"},
                      {"caption", ""},
                      {"ready", false},
                      {"authState", "idle"},
                      {"code", ""},
                      {"error", ""},
                      {"offlineName", ""},
                      {"microsoftName", ""},
                      {"microsoftCaption", ""}};
  QString preferred_id_;
  bool explicit_login_ = false;
  QTimer timer_;
  bool automatic_ = true;
  bool preview_enabled_ = false;
  AccountPort* service_ = nullptr;
};

}  // namespace bugg

#endif  // BUGG_MODULES_ACCOUNT_UI_IDENTITY_SESSION_H_
