#ifndef BUGG_MODULES_MULTIPLAYER_APPLICATION_MULTIPLAYER_SERVICE_H_
#define BUGG_MODULES_MULTIPLAYER_APPLICATION_MULTIPLAYER_SERVICE_H_
#include <QDateTime>
#include <QSet>
#include <QVariantMap>

#include "modules/multiplayer/infrastructure/native_bridge.h"
#include "platform/files/game_files.h"
#include "platform/http/http_client.h"
namespace bugg {
/// 节点登录/房间/好友应用所有者；令牌、设备私钥和节点配置永不暴露给 QML。
class MultiplayerService : public QObject {
  Q_OBJECT
  Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
  Q_PROPERTY(QVariantMap feedback READ feedback NOTIFY changed)
 public:
  MultiplayerService(HttpClient* http, QString cache, QString engine, QObject* parent = nullptr);
  QVariantMap status() const;
  QVariantMap feedback() const { return feedback_; }
  /// 官方入口唯一默认值；空登录参数使用此地址，QML 不保存或展示默认域名。
  static QString default_origin() { return QStringLiteral("https://node.bugg.icu"); }
  /// GUI 异步匿名反馈；基础诊断可选，无日志/凭据。重复提交锁定，关闭取消请求。
  Q_INVOKABLE void submit_feedback(const QString& message, const QString& contact,
                                   bool diagnostics);
  /// 首帧后恢复加密授权；成功后每次启动由原生 RouteSelector 重新测延迟。
  void restore();
  void shutdown();
  bool busy() const { return storage_busy_ || restoring_ || cache_workers_ || bridge_.busy(); }
  void relocate_storage(const QString& cache);
  /// GUI 发起 HTTPS 设备授权；等待授权时复用原链接。失败可重试，退出/登出丢弃迟到响应。
  Q_INVOKABLE void login(const QString& origin = {});
  Q_INVOKABLE void logout();
  /// 定时刷新使用 background；用户搜索默认交互优先，回调仍按登录代次校验。
  Q_INVOKABLE void refresh(const QString& query = {}, bool background = false);
  /// Real bridge routes; -1 restores automatic placement. Only new hosted rooms change node.
  Q_INVOKABLE void refresh_nodes();
  Q_INVOKABLE void select_node(int index);
  /// GUI 标记 rooms/requests 服务通知已读；空类别为全部。无 I/O，重复调用不发 changed。
  Q_INVOKABLE void mark_notifications_read(const QString& category = {});
  /// GUI 异步建房；options 为 instanceId/game/public/requireInvite/port。端口 0 为准备房间。
  /// 校验失败保留表单；leave/logout 使迟到结果失效并关闭迟到创建的会话。
  Q_INVOKABLE void create_room(const QString& title, const QString& directory,
                               const QString& player, const QVariantMap& options = {});
  /// GUI 异步发现本机 LAN 世界，写 status.worlds；重试清错、失败清候选。
  /// 建房/关联中忽略扫描；取消使迟到结果失效。表单默认唯一候选，多个需手选。
  Q_INVOKABLE void discover_worlds();
  /// 验证端口/版本后关联当前房主房间；错误保留准备房间，离开使回调失效。
  Q_INVOKABLE void connect_world(int port);
  /// GUI 复制当前房间邀请到系统剪贴板；没有邀请返回 false，不含账号凭据。
  Q_INVOKABLE bool copy_invite();
  Q_INVOKABLE void join_room(const QString& invite);
  Q_INVOKABLE void join_listing(const QString& id);
  Q_INVOKABLE void leave_room();
  Q_INVOKABLE void social(const QString& operation, const QString& target,
                          const QVariantMap& fields = {});
  /// 短码/用户名查询可取消；不撤销已发出的签名申请。GUI 无阻塞。
  Q_INVOKABLE void cancel_lookup();
  /// GUI 发起好友邀请；未就绪时保留队列并请求开房导航，就绪后自动发送。
  Q_INVOKABLE void invite_friend(const QString& account);
  Q_INVOKABLE void cancel_invites();
  /// 空账号复制自己的公开短码；失败返回 false，绝不复制授权材料。
  Q_INVOKABLE bool copy_friend_code(const QString& account = {});
  /// GUI 当前房间配置/成员命令；异步执行，节点裁决权限，退出使回调失效。
  Q_INVOKABLE void room_command(const QString& operation, const QVariantMap& fields = {});
  /// GUI 发消息；异步确认后展示，离房取消迟到结果；失败保留输入草稿。
  Q_INVOKABLE void send_chat(const QString& text);
  /// GUI 请求同步当前房间的独立实例，由 GameRuntime 的既有任务队列执行。
  Q_INVOKABLE void sync_room(const QString& mode = "fresh");
  /// GUI 选择/核对本地实例；异步只读检查，结果按房间和检查代次拒绝迟到回调。
  Q_INVOKABLE void select_room_instance(const QString& instance_id);
  void content_checked(const QString& session, quint64 revision, const QString& instance_id,
                       const QVariantMap& result);
  /// GUI 房间启动意图；不符时请求准备，成功仍交给同一 LaunchSession 和身份确认。
  Q_INVOKABLE void launch_room();
  /// GUI 接收共享队列结果；只有当前房间真实完成后才绑定启动实例。
  void content_ready(const QString& session, const QString& instance_id, const QString& config);
  /// GUI 接收真实任务/启动状态；同房间、同实例才上报，合并最新进度后异步提交。
  void preparation_progress(const QString& session, const QString& task, const QString& state,
                            double progress, const QString& config = {});
  void launch_progress(const QVariantMap& status);
  /// 工作线程端口：排队到同一个原生通道，等待只发生在工作线程；取消/离房抛异常。
  QJsonObject content_request(const QString& method, QJsonObject parameters,
                              const Cancellation& cancelled);
 signals:
  void changed();
  void restored(const QString& error);
  void drained();
  void room_joined();
  void room_left();
  void social_completed(const QString& operation, const QString& target);
  void host_required();
  void room_command_completed(const QString& operation);
  void chat_sent();
  void sync_requested(const QVariantMap& specification);
  void instance_check_requested(const QString& session, quint64 revision,
                                const QString& instance_id, const QVariantMap& game);
  void content_invalidated(const QString& session);
  void preparation_required();
  void launch_requested(const QString& instance_id, const QVariantMap& contributions);

 private:
  friend class RuntimeTest;
  void post(const QString& path, const QJsonObject& body,
            std::function<void(const QJsonObject&, const QString&)> complete);
  void poll();
  void approved(const QJsonObject& result);
  void connect_profile();
  void persist();
  void report(const QString& error);
  void room_result(const QJsonObject& value, const QString& error);
  void node_routes(const QString& method, const QJsonObject& parameters);
  void complete_room(quint64 operation, const QJsonObject& value, const QString& error);
  void probe_world(int port, const QVariantMap& game, NativeBridge::Reply complete);
  void heartbeat();
  void apply_social(const QJsonObject& value);
  void update_notifications();
  void dispatch_invites();
  void renew_profile();
  void expire_authorization(const QString& error);
  void poll_room();
  void apply_room_events(const QJsonArray& events);
  void announce_room();
  void update_acceleration();
  void report_preparation();
  HttpClient* http_;
  NativeBridge bridge_;
  QTimer polling_, heartbeat_, room_poll_, announcement_, preparation_timer_;
  QVariantMap status_{
      {"state", "signedOut"}, {"rooms", QVariantList{}}, {"friends", QVariantList{}}};
  QString cache_, origin_ = default_origin(), device_id_, nonce_, node_, session_;
  QVariantMap feedback_;
  quint64 feedback_request_ = 0;
  QString feedback_id_, feedback_message_, feedback_contact_;
  bool feedback_diagnostics_ = false;
  QString room_query_;
  QVariantMap pending_room_;
  QVariantMap launch_status_;
  QString room_directory_, cache_key_, preparation_task_, launch_task_;
  Cancellation cache_cancelled_;
  int cache_workers_ = 0;
  QJsonObject preparation_;
  quint64 preparation_sequence_ = 0;
  QByteArray key_;
  QJsonObject profile_;
  QDateTime deadline_;
  QDateTime renewal_retry_;
  QSet<QString> message_ids_;
  int announcement_frame_ = 0;
  quint64 request_ = 0, generation_ = 0;
  quint64 room_generation_ = 0;
  quint64 content_revision_ = 0;
  quint64 lookup_generation_ = 0;
  QStringList pending_invites_;
  QStringList retired_nodes_;
  QSet<QString> ignored_invites_;
  std::function<void(const QJsonObject&, const QString&)> response_;
  bool closing_ = false, restoring_ = false, storage_busy_ = false, storage_pending_ = false,
       room_probe_ = false, event_pending_ = false, renewing_ = false, preparation_pending_ = false;
};
}  // namespace bugg
#endif
